"""Local example preflight, asynchronous runs, evidence, reset and signed callbacks."""

import json
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import Field, StringConstraints
from sqlalchemy import text

from adapters.http.registry import validate_example
from packages.contracts.actors import ActorPolicy
from packages.contracts.config import Identifier, Model
from packages.evidence.store import append
from packages.simulator.e3 import contract, fixtures, new_run, preflight, report, reset_run
from packages.transport.example import Callback
from packages.transport.http import BoundaryError
from packages.transport.security import Scope, digest, verify_signature


class PreflightInput(Model):
    contract_version: Identifier


class RunInput(PreflightInput):
    project_id: UUID
    idempotency_key: Identifier
    suite_scope: Literal["e3_smoke", "e4_core_10", "e5_core_20", "e6_core_20", "e7_core_20"] = "e3_smoke"
    actor_policy: ActorPolicy | None = None
    scenarios: Annotated[
        list[Annotated[str, StringConstraints(pattern=r"^S(0[1-9]|1[0-9]|20)$")]],
        Field(min_length=1, max_length=20),
    ]


def router(db):
    api = APIRouter()

    @api.post("/api/projects/{project_id}/preflight")
    def check(project_id: UUID, body: PreflightInput):
        try:
            return preflight(db, project_id, body.contract_version)
        except BoundaryError as error:
            raise HTTPException(422, str(error)) from None

    @api.post("/api/runs", status_code=202)
    def run(body: RunInput):
        if body.suite_scope == "e7_core_20":
            if body.actor_policy is None:
                body.actor_policy = ActorPolicy()
        elif body.actor_policy is not None:
            raise HTTPException(422, "角色策略只用于 e7_core_20；旧契约和运行保持原语义")
        if len(set(body.scenarios)) != len(body.scenarios):
            raise HTTPException(422, "场景不能重复")
        config, hash_ = contract(db, body.project_id, body.contract_version)
        try:
            validate_example(config)
        except BoundaryError as error:
            raise HTTPException(422, str(error)) from None
        if config.product.adapter == "rpc_credit_v1" and body.suite_scope != "e4_core_10":
            raise HTTPException(422, "第二示例当前只审阅 S01—S10 串行入口 e4_core_10")
        expected = fixtures(body.scenarios)
        if body.suite_scope == "e3_smoke" and (
            set(body.scenarios) - {"S01", "S02"} or config.product.version != "fixed"
        ):
            raise HTTPException(422, "E3 兼容入口仅接受 fixed S01/S02；E4 请设置 suite_scope=e4_core_10")
        if config.environment.currency != "CNY":
            raise HTTPException(422, "E3 场景仅支持 CNY")
        request_data = body.model_dump(mode="json")
        if body.actor_policy is None:
            request_data.pop("actor_policy")
        if body.suite_scope == "e3_smoke":
            # Preserve the original E3 request-key hash after adding the E4 selector.
            request_data.pop("suite_scope")
        payload = {"request": request_data, "expected": expected, "kind": "e3_flow"}
        if body.suite_scope == "e4_core_10" and set(body.scenarios) - {f"S{i:02}" for i in range(1, 11)}:
            raise HTTPException(422, "E4 入口仅支持 S01—S10")
        if body.suite_scope in {"e4_core_10", "e5_core_20", "e6_core_20", "e7_core_20"}:
            from packages.evaluators.refund import RULES
            from packages.simulator.e4 import inputs

            if set(RULES) != {r.id for r in config.rules}:
                raise HTTPException(422, "E4 要求配置全部五条注册规则，不能通过省略规则绕过检查")
            payload = {
                "request": request_data,
                "plan": inputs(body.scenarios),
                "kind": "e4_rules",
            }
        if body.suite_scope in {"e5_core_20", "e6_core_20", "e7_core_20"}:
            from packages.simulator.e5 import FAULTS
            from packages.simulator.e5 import inputs as e5_inputs

            configured = [f.match.scenario_id for f in config.faults]
            if len(set(configured)) != len(configured) or any(
                FAULTS.get(f.match.scenario_id) != f.behavior for f in config.faults
            ):
                raise HTTPException(422, "E5 核心场景每场景只允许相应边界的一个故障计划")

            payload = {
                "request": request_data,
                "plan": e5_inputs(body.scenarios, config),
                "kind": "e5_runtime",
            }
        if body.suite_scope in {"e6_core_20", "e7_core_20"}:
            from packages.simulator.replay import semantic_faults

            try:
                payload["plan"] = semantic_faults(payload["plan"])
            except BoundaryError as error:
                raise HTTPException(422, str(error)) from None
            payload["kind"] = "e6_replay"
        scope = Scope(project_id=body.project_id, run_id=uuid4())
        with db.begin() as c:
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"),
                {"k": str(body.project_id) + ":" + body.idempotency_key},
            )
            old = (
                c.execute(
                    text(
                        "SELECT r.run_id,i.request_hash FROM runs r JOIN run_inputs i USING(project_id,run_id) WHERE r.project_id=:p AND i.request_key=:k"
                    ),
                    {"p": body.project_id, "k": body.idempotency_key},
                )
                .mappings()
                .first()
            )
            if old:
                if old["request_hash"] != digest(request_data):
                    raise HTTPException(409, "请求幂等键对应不同输入")
                return {"run_id": str(old["run_id"]), "project_id": str(body.project_id), "reused": True}
            active = c.execute(
                text(
                    "SELECT passed FROM preflights WHERE project_id=:p AND contract_hash=:h ORDER BY created_at DESC LIMIT 1"
                ),
                {"p": body.project_id, "h": hash_},
            ).scalar()
            if active is not True:
                raise HTTPException(409, "该契约尚未通过接入预检")
            binding = new_run(c, scope, body.contract_version, config, payload)
            if body.suite_scope in {"e6_core_20", "e7_core_20"}:
                from packages.simulator.replay import freeze

                freeze(
                    c,
                    scope,
                    config,
                    payload["plan"],
                    binding,
                    body.contract_version,
                    actor_policy=body.actor_policy,
                )
            elif body.suite_scope == "e5_core_20":
                from packages.simulator.e5 import freeze

                freeze(c, scope, config, payload["plan"], binding)
            c.execute(
                text("INSERT INTO jobs (project_id,run_id,job_id,idempotency_key) VALUES (:p,:r,:j,:key)"),
                scope.params | {"j": uuid4(), "key": body.idempotency_key},
            )
        return {
            "run_id": str(scope.run_id),
            "project_id": str(body.project_id),
            "status": "queued",
            "verdict": "inconclusive",
        }

    @api.get("/api/runs/{run_id}")
    def get_run(run_id: UUID, project_id: UUID):
        with db.connect() as c:
            row = (
                c.execute(
                    text("SELECT * FROM runs WHERE project_id=:p AND run_id=:r"),
                    {"p": project_id, "r": run_id},
                )
                .mappings()
                .first()
            )
        if not row:
            raise HTTPException(404, "run 不存在")
        result = dict(row)
        if row["status"] in {"completed", "failed", "cancelled"}:
            with db.connect() as c:
                kind = c.execute(
                    text("SELECT payload->>'kind' FROM run_inputs WHERE project_id=:p AND run_id=:r"),
                    {"p": project_id, "r": run_id},
                ).scalar()
            if kind in {"e4_rules", "e5_runtime", "e6_replay"}:
                from packages.evaluators.reporting import report as e4_report

                result["verdict"] = e4_report(db, Scope(project_id=project_id, run_id=run_id))["verdict"]
        return result

    @api.get("/api/runs/{run_id}/report")
    def get_report(run_id: UUID, project_id: UUID, format: Literal["json", "html"] = "json"):
        get_run(run_id, project_id)
        scope = Scope(project_id=project_id, run_id=run_id)
        with db.connect() as c:
            data = (
                c.execute(
                    text("SELECT payload FROM run_inputs WHERE project_id=:p AND run_id=:r"), scope.params
                ).scalar()
                or {}
            )
            has_e4 = c.execute(
                text("SELECT 1 FROM evaluations WHERE project_id=:p AND run_id=:r LIMIT 1"), scope.params
            ).scalar()
        if data.get("kind") in {"e4_rules", "e5_runtime", "e6_replay"} or has_e4:
            from packages.evaluators.reporting import render_html
            from packages.evaluators.reporting import report as e4_report

            result = e4_report(db, scope)
            if format == "html":
                return HTMLResponse(
                    render_html(result),
                    headers={
                        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
                    },
                )
            return result
        if format == "html":
            raise HTTPException(422, "E3 历史入口仅提供 JSON；HTML 适用于 E4 运行")
        return report(db, scope)

    @api.get("/api/runs/{run_id}/events")
    def events(
        run_id: UUID, project_id: UUID, after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
    ):
        get_run(run_id, project_id)
        with db.connect() as c:
            rows = (
                c.execute(
                    text(
                        "SELECT * FROM events WHERE project_id=:p AND run_id=:r AND ingress_sequence>:after ORDER BY ingress_sequence LIMIT :limit"
                    ),
                    {"p": project_id, "r": run_id, "after": after, "limit": limit},
                )
                .mappings()
                .all()
            )
        return {
            "items": [dict(r) for r in rows],
            "next_cursor": rows[-1]["ingress_sequence"] if rows else after,
        }

    @api.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: UUID, project_id: UUID):
        get_run(run_id, project_id)
        from packages.simulator.jobs import cancel

        try:
            return cancel(db, Scope(project_id=project_id, run_id=run_id))
        except BoundaryError as error:
            raise HTTPException(409, str(error)) from None

    @api.post("/api/runs/{run_id}/reset")
    def reset(run_id: UUID, project_id: UUID):
        row = get_run(run_id, project_id)
        config, _ = contract(db, project_id, row["contract_version"])
        try:
            return reset_run(db, Scope(project_id=project_id, run_id=run_id), config)
        except BoundaryError as error:
            raise HTTPException(503, str(error)) from None

    @api.post("/api/webhooks/{binding_id}")
    async def webhook(binding_id: UUID, request: Request):
        body = await request.body()
        if len(body) > 65536:
            raise HTTPException(413, "回调超过 64 KiB")
        with db.connect() as c:
            binding = (
                c.execute(text("SELECT * FROM webhook_bindings WHERE binding_id=:id"), {"id": binding_id})
                .mappings()
                .first()
            )
        if not binding:
            raise HTTPException(404, "Webhook 绑定不存在")
        scope = Scope(project_id=binding["project_id"], run_id=binding["run_id"])
        verify_signature(
            scope,
            request.headers.get("X-Webhook-Timestamp"),
            body,
            request.headers.get("X-Webhook-Signature"),
        )
        try:
            value = json.loads(body)
        except ValueError:
            raise HTTPException(422, "回调 JSON 格式无效") from None
        if not isinstance(value, dict):
            raise HTTPException(422, "回调必须是 JSON 对象")
        if value.get("project_id") != str(scope.project_id) or value.get("run_id") != str(scope.run_id):
            raise HTTPException(403, "回调命名空间不匹配")
        try:
            event = Callback.model_validate(value)
        except ValueError:
            # Authenticated raw business values are evidence, even when they violate
            # the provider wire schema. Keep them; a 422 must not erase counterevidence.
            with db.begin() as c:
                append(c, scope, "provider_webhook", "invalid-protocol", "dependency_evidence", value)
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=422, content={"detail": "回调格式无效；已验签的原始观测已保留"})
        hash_ = digest(value)
        with db.begin() as c:
            # Serializes duplicate delivery; commits observation and receipt before HTTP acknowledgement.
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"),
                {"k": "webhook:" + scope.namespace},
            )
            active = c.execute(
                text("SELECT 1 FROM webhook_bindings WHERE binding_id=:id FOR SHARE"), {"id": binding_id}
            ).scalar()
            if not active:
                raise HTTPException(404, "绑定已 reset")
            old = c.execute(
                text("SELECT digest FROM webhook_receipts WHERE project_id=:p AND run_id=:r AND event_id=:e"),
                scope.params | {"e": event.event_id},
            ).scalar()
            if old:
                if old != hash_:
                    # Commit the conflicting, validly signed source too. Raising inside
                    # this transaction would roll it back and erase the contradiction.
                    append(c, scope, "provider_webhook", str(event.event_id), "dependency_evidence", value)
                    from fastapi.responses import JSONResponse

                    return JSONResponse(
                        status_code=409, content={"detail": "重复事件 ID 的内容不一致；双方证据已保留"}
                    )
                return {"accepted": True, "duplicate": True}
            observation_id = append(
                c, scope, "provider_webhook", str(event.event_id), "dependency_evidence", value
            )
            c.execute(
                text("INSERT INTO webhook_receipts VALUES (:p,:r,:e,:h,:o)"),
                scope.params | {"e": event.event_id, "h": hash_, "o": UUID(observation_id)},
            )
        return {"accepted": True, "duplicate": False}

    from services.api.experiments import router as experiment_router

    api.include_router(experiment_router(db, run))
    return api
