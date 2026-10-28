"""E8 read models over existing contracts, jobs and independently evaluated evidence.

No UI verdicts, alternative execution state, remote credentials or demo success paths.
"""

from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from packages.contracts.config import parse_yaml
from packages.evaluators.reporting import report
from packages.simulator.e3 import contract
from packages.simulator.replay import BOUNDARY
from packages.transport.security import Scope

TERMINAL = {"completed", "failed", "cancelled"}
SCENARIO_NAMES = [
    "阈值以下及相等点退款",
    "有效审批退款",
    "大额未审批",
    "审批后修改金额",
    "同指令重复提交",
    "合法多次部分退款",
    "累计超额退款",
    "币种不匹配",
    "低权限审批",
    "跨客户查询",
    "支付提交前连接中断",
    "支付提交后响应丢失",
    "重复回调",
    "回调乱序",
    "限流与恢复",
    "同指令并发执行",
    "部分退款竞争余额",
    "审批人离线",
    "取消与执行竞争",
    "Worker 中断恢复",
]


def page(items, total, limit, offset):
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def require_project(db, project_id):
    with db.connect() as c:
        row = c.execute(text("SELECT * FROM projects WHERE id=:p"), {"p": project_id}).mappings().first()
    if not row:
        raise HTTPException(404, "项目不存在")
    return dict(row)


def run_view(db, scope):
    with db.connect() as c:
        row = (
            c.execute(text("SELECT * FROM runs WHERE project_id=:p AND run_id=:r"), scope.params)
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "运行不存在或不属于当前项目")
        job = (
            c.execute(
                text(
                    "SELECT state,heartbeat,expires_at,checkpoint,cancel_requested,clock_timestamp() AS db_now FROM jobs WHERE project_id=:p AND run_id=:r"
                ),
                scope.params,
            )
            .mappings()
            .first()
        )
        states = dict(
            c.execute(
                text(
                    "SELECT state,count(*) FROM event_dispatches WHERE project_id=:p AND run_id=:r GROUP BY state"
                ),
                scope.params,
            ).all()
        )
        payload = (
            c.execute(
                text("SELECT payload FROM run_inputs WHERE project_id=:p AND run_id=:r"), scope.params
            ).scalar()
            or {}
        )
    result = dict(row)
    assessment = (
        report(db, scope)
        if row["status"] in TERMINAL and payload.get("kind") in {"e4_rules", "e5_runtime", "e6_replay"}
        else None
    )
    if assessment:
        result["verdict"] = assessment["verdict"]
    worker = "not_running"
    if row["status"] not in TERMINAL:
        worker = "waiting"
        if job and job["state"] == "leased":
            worker = "lost" if job["expires_at"] <= job["db_now"] else "active"
    return {
        "run": result,
        "example": True,
        "worker": {
            "state": worker,
            "heartbeat": job and job["heartbeat"],
            "expires_at": job and job["expires_at"],
            "cancel_requested": bool(job and job["cancel_requested"]),
        },
        "progress": {"total": sum(states.values()), "states": states},
        "selected_scenarios": payload.get("request", {}).get("scenarios", []),
        "budget_used": dict(job["checkpoint"]) if job else {},
        "report": {
            k: v for k, v in assessment.items() if k not in {"observations", "runtime", "checks", "findings"}
        }
        if assessment
        else None,
        "finding_count": len(assessment["findings"]) if assessment else None,
        "runtime_summary": {
            k: v
            for k, v in assessment.get("runtime", {}).items()
            if k not in {"events", "actions", "journal"}
        }
        if assessment
        else None,
    }


def project_summary(db, project):
    p = project["id"]
    with db.connect() as c:
        versions = (
            c.execute(
                text(
                    "SELECT DISTINCT config->'product'->>'version' AS version FROM contracts WHERE project_id=:p ORDER BY version"
                ),
                {"p": p},
            )
            .scalars()
            .all()
        )
        latest = c.execute(
            text(
                "SELECT r.run_id FROM runs r JOIN jobs j USING(project_id,run_id) WHERE r.project_id=:p ORDER BY r.created_at DESC,r.run_id DESC LIMIT 1"
            ),
            {"p": p},
        ).scalar()
    return dict(project) | {
        "product_versions": versions,
        "latest_run": run_view(db, Scope(project_id=p, run_id=latest))["run"] if latest else None,
    }


def current_finding(db, scope, finding_id):
    data = report(db, scope)
    finding = next((f for f in data["findings"] if f["finding_id"] == str(finding_id)), None)
    if finding is None:
        raise HTTPException(404, "当前证据中没有此 Finding；证据可能已被重置，请返回运行重新读取结论")
    return data, finding


def router(db):
    api = APIRouter()

    @api.get("/api/console/catalog")
    def catalog():
        yaml = (
            Path(__file__).resolve().parents[2] / "environments/refund_approval/local.e5.yaml"
        ).read_text()
        return {
            "example": True,
            "template_yaml": yaml,
            "config": parse_yaml(yaml).model_dump(mode="json"),
            "product_versions": ["buggy", "fixed"],
            "suite_scope": "e7_core_20",
            "scenarios": [{"id": f"S{i:02}", "name": name} for i, name in enumerate(SCENARIO_NAMES, 1)],
            "time_modes": [
                {
                    "id": "event_compressed",
                    "name": "事件压缩",
                    "supported": True,
                    "description": "压缩平台日程间隔；产品、支付依赖与观察窗口仍使用真实墙钟。",
                },
                {
                    "id": "realtime",
                    "name": "实时",
                    "supported": True,
                    "description": "按真实时间推进平台日程；不控制产品时钟、网络延迟和数据库锁顺序。",
                },
                {
                    "id": "controlled",
                    "name": "受控时钟（未支持）",
                    "supported": False,
                    "description": "当前产品没有可控时钟接口；不能选择。受控输入重放不等于受控时钟。",
                },
            ],
            "control_boundary": BOUNDARY,
            "model": {
                "supported": False,
                "reason": "示例产品没有自然语言入口；使用规则角色，真实模型实验未执行。",
            },
        }

    @api.get("/api/projects/{project_id}")
    def project(project_id: UUID):
        return project_summary(db, require_project(db, project_id))

    @api.get("/api/projects/{project_id}/contracts")
    def contracts(project_id: UUID, limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)):
        require_project(db, project_id)
        with db.connect() as c:
            rows = (
                c.execute(
                    text(
                        "SELECT c.*, (SELECT payload FROM preflights p WHERE p.project_id=c.project_id AND p.contract_hash=c.content_hash ORDER BY created_at DESC LIMIT 1) AS preflight FROM contracts c WHERE c.project_id=:p ORDER BY created_at DESC,version LIMIT :limit OFFSET :offset"
                    ),
                    {"p": project_id, "limit": limit, "offset": offset},
                )
                .mappings()
                .all()
            )
            total = c.execute(
                text("SELECT count(*) FROM contracts WHERE project_id=:p"), {"p": project_id}
            ).scalar_one()
        return page([dict(r) for r in rows], total, limit, offset)

    @api.get("/api/projects/{project_id}/preflight")
    def latest_preflight(project_id: UUID, contract_version: str):
        _, hash_ = contract(db, project_id, contract_version)
        with db.connect() as c:
            row = c.execute(
                text(
                    "SELECT payload FROM preflights WHERE project_id=:p AND contract_hash=:h ORDER BY created_at DESC LIMIT 1"
                ),
                {"p": project_id, "h": hash_},
            ).scalar()
        return {"result": row}

    @api.get("/api/projects/{project_id}/runs")
    def runs(project_id: UUID, limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)):
        require_project(db, project_id)
        with db.connect() as c:
            ids = (
                c.execute(
                    text(
                        "SELECT r.run_id FROM runs r JOIN jobs j USING(project_id,run_id) WHERE r.project_id=:p ORDER BY r.created_at DESC,r.run_id DESC LIMIT :limit OFFSET :offset"
                    ),
                    {"p": project_id, "limit": limit, "offset": offset},
                )
                .scalars()
                .all()
            )
            total = c.execute(
                text("SELECT count(*) FROM jobs WHERE project_id=:p"), {"p": project_id}
            ).scalar_one()
        return page(
            [run_view(db, Scope(project_id=project_id, run_id=r))["run"] for r in ids], total, limit, offset
        )

    @api.get("/api/runs/{run_id}/console")
    def console(run_id: UUID, project_id: UUID):
        return run_view(db, Scope(project_id=project_id, run_id=run_id))

    @api.get("/api/runs/{run_id}/findings")
    def findings(
        run_id: UUID, project_id: UUID, limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        result = report(db, Scope(project_id=project_id, run_id=run_id))
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        values = sorted(result["findings"], key=lambda f: (rank[f["severity"]], f["finding_id"]))
        return page(values[offset : offset + limit], len(values), limit, offset)

    @api.get("/api/runs/{run_id}/checks")
    def checks(
        run_id: UUID, project_id: UUID, limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        result = report(db, Scope(project_id=project_id, run_id=run_id))
        rank = {"fail": 0, "inconclusive": 1, "pass": 2, "not_applicable": 3}
        values = sorted(result["checks"], key=lambda c: (rank[c["verdict"]], c["rule_id"], c["object_id"]))
        return page(values[offset : offset + limit], len(values), limit, offset)

    @api.get("/api/runs/{run_id}/findings/{finding_id}")
    def finding(
        run_id: UUID,
        finding_id: UUID,
        project_id: UUID,
        limit: int = Query(5, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        data, value = current_finding(db, Scope(project_id=project_id, run_id=run_id), finding_id)
        observations = [o for o in data["observations"] if str(o["observation_id"]) in value["evidence_refs"]]
        observations.sort(
            key=lambda o: (o["source"] != "provider_ledger", str(o["captured_at"]), str(o["observation_id"]))
        )
        return {
            "finding": value,
            "run_verdict": data["verdict"],
            "example": data["example"],
            "rule": next((r for r in data["rules"] if r["id"] == value["rule_id"]), None),
            "rules_hash": data["versions"]["rules_hash"],
            "evaluation_rule_version": data["versions"]["rule_version"],
            "missing_evidence_refs": sorted(
                set(value["evidence_refs"]) - {str(o["observation_id"]) for o in observations}
            ),
            "evidence": page(observations[offset : offset + limit], len(observations), limit, offset),
        }

    @api.get("/api/runs/{run_id}/timeline")
    def timeline(
        run_id: UUID,
        project_id: UUID,
        lane: Literal["all", "actor", "product", "provider", "evaluator"] = "all",
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        scope = Scope(project_id=project_id, run_id=run_id)
        with db.connect() as c:
            if not c.execute(
                text("SELECT 1 FROM runs WHERE project_id=:p AND run_id=:r"), scope.params
            ).scalar():
                raise HTTPException(404, "运行不存在或不属于当前项目")
            # All links are actual stored IDs; wall-time order alone never implies causality.
            query = """
            WITH items AS (
              SELECT a.action_id::text AS id, 'actor' AS lane,a.start_time AS wall_time,
                e.simulation_time,a.operation AS title,e.business_object_id AS object_id,
                a.event_id::text AS event_id,e.causation_id::text AS causation_id,
                jsonb_build_object('actor_id',a.actor_id,'end_time',a.end_time,'request_ref',a.request_ref) AS detail
              FROM actions a JOIN events e USING(project_id,run_id,event_id) WHERE a.project_id=:p AND a.run_id=:r
              UNION ALL
              SELECT o.observation_id::text,CASE WHEN o.evidence_kind='dependency_evidence' THEN 'provider' ELSE 'product' END,
                o.captured_at,e.simulation_time,o.source || ' · ' || COALESCE(o.payload->'request'->>'path','webhook'),
                o.external_id,a.event_id::text,a.action_id::text,
                jsonb_build_object('source',o.source,'status',o.payload->'response'->'status','digest',o.digest,'observation_id',o.observation_id)
              FROM observations o LEFT JOIN actions a ON a.project_id=o.project_id AND a.run_id=o.run_id AND a.request_ref='private://postgres/' || o.project_id::text || '/' || o.run_id::text || '/' || o.observation_id::text
              LEFT JOIN events e ON e.project_id=a.project_id AND e.run_id=a.run_id AND e.event_id=a.event_id
              WHERE o.project_id=:p AND o.run_id=:r
              UNION ALL
              SELECT c.check_id::text,'evaluator',c.evaluated_at,NULL,c.rule_id,c.object_id,NULL,NULL,
                jsonb_build_object('verdict',c.verdict,'reason',c.reason,'evidence_refs',c.evidence_refs,'rule_version',c.rule_version)
              FROM check_results c WHERE c.project_id=:p AND c.run_id=:r
                AND c.evaluation_id=(SELECT evaluation_id FROM evaluations WHERE project_id=:p AND run_id=:r ORDER BY created_at DESC LIMIT 1)
            ) SELECT *,count(*) OVER() AS total FROM items WHERE (:lane='all' OR lane=:lane) ORDER BY wall_time,id LIMIT :limit OFFSET :offset
            """
            rows = [
                dict(r)
                for r in c.execute(
                    text(query), scope.params | {"limit": limit, "offset": offset, "lane": lane}
                ).mappings()
            ]
            total = (
                rows[0]["total"]
                if rows
                else c.execute(
                    text(
                        query.partition("SELECT *,count(*) OVER() AS total")[0]
                        + "SELECT count(*) FROM items WHERE (:lane='all' OR lane=:lane)"
                    ),
                    scope.params | {"lane": lane},
                ).scalar_one()
            )
        return page(rows, total, limit, offset) | {
            "causal_note": "按真实墙钟排列；因果关系仅由 event、causation 与 evidence_refs 表达。未关联观测不会推测前驱。"
        }

    return api
