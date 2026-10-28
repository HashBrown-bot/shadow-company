"""Evidence-based E4 reports and append-only evaluation snapshots."""

import html
import json
from collections import Counter
from dataclasses import asdict
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from packages.evaluators.gates import gate_result
from packages.evaluators.refund import Policy, evaluate
from packages.simulator.e3 import contract
from packages.simulator.e4 import SCENARIOS
from packages.transport.build import provenance
from packages.transport.security import canonical, digest, redact

LIMITS = [
    "本机明确标记的示例 PUT/provider；没有真实资金、客户或生产验证",
    "E4 串行 S01—S10；S11—S20、故障注入、barrier、取消与自动恢复未验收",
    "本运行的业务套件与平台整体工程验收分开；当前交付状态见 docs/release-checklist.md",
    "时间判定使用真实墙钟；event_compressed 不控制外部时钟",
    "同一开发数据库账号下的独立 schema；不是数据库账号或 OS 安全隔离",
]


def report(db, scope):
    with db.connect() as c:
        run = (
            c.execute(text("SELECT * FROM runs WHERE project_id=:p AND run_id=:r"), scope.params)
            .mappings()
            .first()
        )
        if run is None:
            raise HTTPException(404, "run 不存在")
        inputs = (
            c.execute(text("SELECT * FROM run_inputs WHERE project_id=:p AND run_id=:r"), scope.params)
            .mappings()
            .one()
        )
        observations = [
            dict(o)
            for o in c.execute(
                text(
                    "SELECT * FROM observations WHERE project_id=:p AND run_id=:r ORDER BY captured_at,observation_id"
                ),
                scope.params,
            ).mappings()
        ]
        budget = (
            c.execute(
                text("SELECT checkpoint FROM jobs WHERE project_id=:p AND run_id=:r"), scope.params
            ).scalar()
            or {}
        )
    e6 = inputs["payload"].get("kind") == "e6_replay"
    e5 = inputs["payload"].get("kind") in {"e5_runtime", "e6_replay"}
    runtime = None
    if e5:
        from packages.evaluators.runtime import runtime_evidence, scenario_verified

        runtime = runtime_evidence(db, scope, inputs["payload"], observations)
    config, _ = contract(db, scope.project_id, run["contract_version"])
    policy = Policy.from_config(config)
    assessment = evaluate(policy, observations, scope, completed=run["status"] == "completed")
    # Dedup by rule, business object and established external failure, not event count.
    unique = {}
    for finding in assessment["findings"]:
        key = finding["dedup_key"]
        if key not in unique:
            unique[key] = finding
        else:
            unique[key]["evidence_refs"] = sorted(
                set(unique[key]["evidence_refs"] + finding["evidence_refs"])
            )
    assessment["findings"] = list(unique.values())
    evidence_hash = digest(
        [
            {
                k: o[k]
                for k in (
                    "observation_id",
                    "digest",
                    "captured_at",
                    "source",
                    "evidence_kind",
                    "project_id",
                    "run_id",
                )
            }
            for o in observations
        ]
    )
    # Include the freshly derived outcome: an expired TIME deadline changes the snapshot
    # even if no new observations arrive. Never trust a cached success on evidence loss.
    signature = digest(
        {
            "evidence": evidence_hash,
            "status": run["status"],
            "stop_reason": run["stop_reason"],
            "checks": [
                {k: c[k] for k in ("rule_id", "object_id", "verdict", "reason", "evidence_refs")}
                for c in assessment["checks"]
            ],
            "access": assessment["access_checks"],
        }
    )
    with db.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "evaluation:" + scope.namespace},
        )
        previous = (
            c.execute(
                text(
                    "SELECT evaluation_id,payload FROM evaluations WHERE project_id=:p AND run_id=:r AND evidence_hash=:h AND rules_hash=:rules ORDER BY created_at DESC LIMIT 1"
                ),
                scope.params | {"h": signature, "rules": policy.content_hash()},
            )
            .mappings()
            .first()
        )
        if previous:
            assessment = previous["payload"]
            evaluation_id = str(previous["evaluation_id"])
        else:
            evaluation_id = str(uuid4())
            known = {
                row["dedup_key"]: str(row["finding_id"])
                for row in c.execute(
                    text("SELECT dedup_key,finding_id FROM findings WHERE project_id=:p AND run_id=:r"),
                    scope.params,
                ).mappings()
            }
            for finding in assessment["findings"]:
                if finding["dedup_key"] in known:
                    finding["finding_id"] = known[finding["dedup_key"]]
            c.execute(
                text(
                    "INSERT INTO evaluations(project_id,run_id,evaluation_id,evidence_hash,rules_hash,payload) VALUES (:p,:r,:id,:h,:rules,CAST(:v AS jsonb))"
                ),
                scope.params
                | {
                    "id": evaluation_id,
                    "h": signature,
                    "rules": policy.content_hash(),
                    "v": canonical(assessment),
                },
            )
            for check in assessment["checks"]:
                c.execute(
                    text("""INSERT INTO check_results(project_id,run_id,check_id,rule_id,rule_version,object_id,verdict,reason,evidence_refs,evaluated_at,evaluation_id)
                    VALUES (:p,:r,:check_id,:rule_id,:rule_version,:object_id,:verdict,:reason,CAST(:refs AS jsonb),:evaluated_at,:evaluation)"""),
                    scope.params
                    | check
                    | {"refs": canonical(check["evidence_refs"]), "evaluation": evaluation_id},
                )
            for finding in assessment["findings"]:
                c.execute(
                    text("""INSERT INTO findings(project_id,run_id,finding_id,check_id,severity,attribution,confirmation,dedup_key,payload)
                    VALUES (:p,:r,:finding_id,:check_id,:severity,:attribution,:confirmation,:dedup_key,CAST(:v AS jsonb))
                    ON CONFLICT(project_id,run_id,dedup_key) DO UPDATE SET
                    check_id=EXCLUDED.check_id,severity=EXCLUDED.severity,attribution=EXCLUDED.attribution,
                    confirmation=EXCLUDED.confirmation,payload=EXCLUDED.payload"""),
                    scope.params | finding | {"v": canonical(finding)},
                )
    selected = inputs["payload"].get("request", {}).get("scenarios", [])
    mapping = inputs["payload"].get("plan", {}).get("scenario_objects", {})
    coverage = []
    observed_actions = Counter()
    for observation in observations:
        payload = observation.get("payload", {})
        request = payload.get("request", {})
        if observation["source"] == "put" and isinstance(request, dict):
            observed_actions[
                (
                    request.get("method"),
                    request.get("path"),
                    payload.get("actor_id"),
                    digest(request.get("body")),
                )
            ] += 1
    if e5:
        for event in runtime["events"]:
            if (
                str(event["event_id"]) in runtime["recovered_event_ids"]
                and event["payload"]["operation"] == "execute_refund"
            ):
                spec = event["payload"]
                observed_actions[(spec["method"], spec["path"], spec["role"], digest(spec["body"]))] += 1
    for s in tuple(f"S{i:02}" for i in range(1, 21)) if e5 else SCENARIOS:
        relevant = [
            v
            for v in assessment["checks"] + assessment["access_checks"]
            if v["object_id"] in mapping.get(s, [])
        ]
        expected_objects = set(mapping.get(s, []))
        done = (
            s in selected
            and run["status"] == "completed"
            and bool(relevant)
            and expected_objects <= {v["object_id"] for v in relevant}
        )
        required_actions = Counter()
        for step in inputs["payload"].get("plan", {}).get("steps", []):
            if step["scenario_id"] != s:
                continue
            if e5:
                from packages.simulator.e5 import wire

                method, path = wire(step, config)
            elif step["operation"] == "amend_refund":
                method, path = "PATCH", "/refunds/" + step["command_id"]
            else:
                endpoint = getattr(config.product.actions, step["operation"])
                method, path = endpoint.method, endpoint.path.replace("{refund_id}", step["command_id"])
            required_actions[(method, path, step["role"], digest(redact(step["body"])))] += 1
        done = done and bool(required_actions) and not (required_actions - observed_actions)
        if e5:
            done = done and scenario_verified(s, runtime)
        verdict = (
            "fail"
            if any(v["verdict"] == "fail" for v in relevant)
            else "inconclusive"
            if not done or any(v["verdict"] == "inconclusive" for v in relevant)
            else "pass"
        )
        if s == "S10" and done and not assessment["access_checks"]:
            verdict = "inconclusive"
        coverage.append(
            {
                "scenario_id": s,
                "selected": s in selected,
                "status": "executed" if done else "unverified",
                "verdict": verdict,
                "object_ids": mapping.get(s, []),
                "actions_required": sum(required_actions.values()),
                "actions_observed": sum((required_actions & observed_actions).values()),
                "evidence_refs": sorted({r for v in relevant for r in v["evidence_refs"]}),
            }
        )
    selected_verdict = assessment["verdict"]
    if (
        not selected
        or any(c["selected"] and c["verdict"] == "inconclusive" for c in coverage)
        and selected_verdict != "fail"
    ):
        selected_verdict = "inconclusive"
    unverified = [c["scenario_id"] for c in coverage if c["status"] != "executed"] + [
        f"S{i:02}" for i in ([] if e5 else range(11, 21))
    ]
    if run["status"] == "completed":
        with db.begin() as c:
            c.execute(
                text("UPDATE runs SET verdict=:v WHERE project_id=:p AND run_id=:r AND status='completed'"),
                scope.params | {"v": selected_verdict},
            )
    result = {
        "schema_version": "e5-report-1" if e5 else "e4-report-1",
        "example": True,
        "project_id": str(scope.project_id),
        "run_id": str(scope.run_id),
        "status": run["status"],
        "verdict": selected_verdict,
        "stop_reason": run["stop_reason"],
        "scope": {
            "phase": "E5" if e5 else "E4",
            "selected_scenarios": selected,
            "responsibility": config.product.responsibility,
            "currency_policy": "逐支付、逐币种累计成功执行；失败尝试不计入",
        },
        "versions": {
            "contract": run["contract_version"],
            "contract_hash": run["contract_hash"],
            "product": run["put_version"],
            "adapter": config.product.adapter,
            "environment": config.environment.version,
            "rules_hash": policy.content_hash(),
            "rule_version": policy.version,
            "evaluator_build": provenance()["rules"],
            "schema_revision": "0004_e5" if e5 else "0003_e4",
            "input_hash": inputs["content_hash"],
        },
        "rules": [r.model_dump() for r in config.rules],
        "policy": asdict(policy),
        "evaluation_id": evaluation_id,
        "evidence_hash": evidence_hash,
        "checks": assessment["checks"],
        "findings": assessment["findings"],
        "distribution": assessment["distribution"],
        "access_checks": assessment["access_checks"],
        "observation_conflicts": assessment["observation_conflicts"],
        "evidence_issues": assessment["evidence_issues"],
        "execution_issues": [],
        "observation_window": assessment["observation_window"],
        "coverage": coverage,
        "observations": observations,
        "unverified": unverified
        + [
            c["rule_id"] + ":" + c["object_id"]
            for c in assessment["checks"]
            if c["verdict"] == "inconclusive"
        ],
        "budget": {
            "limits": config.runtime.model_dump(),
            "used": budget,
            "cost": {
                "model_calls": 0,
                "model_tokens": 0,
                "source": "模型关闭，无模型费用；未估算基础设施成本",
            },
        },
        "selected_gate": {"scope": "E4 selected scenarios", "verdict": selected_verdict},
        "gate": {
            "suite": config.suite,
            "verdict": "fail" if selected_verdict == "fail" else "inconclusive",
            "reason": "此运行仅选择 E4 串行范围，S11—S20 未验证；不得将其通过视为完整 V2 通过",
        },
        "attribution_counts": dict(Counter(f["attribution"] for f in assessment["findings"])),
        "limits": LIMITS,
        "replay": {"capability": "unavailable", "reason": "E6 尚未实施"},
    }

    if e5:
        result["runtime"] = runtime
        result["selected_gate"]["scope"] = "E5 selected scenarios"
        result["limits"] = [x for x in LIMITS if not x.startswith("E4 串行")]
        result["gate"]["verdict"] = (
            "fail"
            if selected_verdict == "fail"
            else "pass"
            if selected_verdict == "pass" and not unverified
            else "inconclusive"
        )
        result["gate"]["reason"] = "仅 refund_core_20 业务套件；不代表平台整体工程、客户或生产验收"
        result["runtime"]["performance"]["generator_wall_seconds"] = budget.get("wall_seconds")
    if e6:
        from packages.simulator.replay import replay_report, seal_run

        result = replay_report(db, scope, result)
        from packages.simulator.actors import actor_report

        result = actor_report(db, scope, result)
        seal_run(db, scope, result)
        if run["status"] == "completed":
            with db.begin() as c:
                c.execute(
                    text(
                        "UPDATE runs SET verdict=:v WHERE project_id=:p AND run_id=:r AND status='completed'"
                    ),
                    scope.params | {"v": result["verdict"]},
                )
    result["ci_gates"] = {
        selection: gate_result(result, selection, config.gate.required_checks)
        for selection in ("selected", "suite")
    }
    return result


def render_html(report):
    def esc(value):
        return html.escape(str(value), quote=True)

    def dump(value):
        return esc(json.dumps(value, ensure_ascii=False, indent=2, default=str))

    labels = {str(o["observation_id"]): f"E{i + 1}" for i, o in enumerate(report["observations"])}
    rank = {"fail": 0, "inconclusive": 1, "pass": 2, "not_applicable": 3}
    ordered = sorted(report["checks"], key=lambda c: (rank[c["verdict"]], c["object_id"], c["rule_id"]))
    rows = ""
    for check in ordered:
        links = " ".join(
            f'<a href="#e-{esc(ref)}" title="{esc(ref)}">{labels.get(ref, esc(ref))}</a>'
            for ref in check["evidence_refs"]
        )
        rows += f'<tr><td>{esc(check["rule_id"])}</td><td>{esc(check["object_id"])}</td><td class="{esc(check["verdict"])}">{esc(check["verdict"])}</td><td>{esc(check["reason"])}</td><td>{links}</td></tr>'
    evidence = "".join(
        f'<details id="e-{esc(o["observation_id"])}"><summary>{labels[str(o["observation_id"])]} · {esc(o["source"])} · {esc(o["observation_id"])}</summary><pre>{dump(o)}</pre></details>'
        for o in report["observations"]
    )
    sections = "".join(
        f'<details class="section"><summary>{title}</summary><pre>{dump(report[key])}</pre></details>'
        for title, key in [
            ("范围", "scope"),
            ("版本与内容哈希", "versions"),
            ("规则", "rules"),
            ("场景覆盖", "coverage"),
            ("发现与已观测失败链", "findings"),
            ("客户读取权限", "access_checks"),
            ("冲突来源", "observation_conflicts"),
            ("证据问题", "evidence_issues"),
            ("观察窗口", "observation_window"),
            ("未验证项", "unverified"),
            ("预算与费用来源", "budget"),
            ("完整套件 gate", "gate"),
            ("限制", "limits"),
            ("重放模式、Manifest、fixture 偏离与控制边界", "replay"),
        ]
    )
    if "runtime" in report:
        sections += (
            '<details class="section"><summary>事件、故障、并发、恢复与分项耗时</summary><pre>'
            + dump(report["runtime"])
            + "</pre></details>"
        )
    if report.get("execution_issues"):
        sections += (
            '<details class="section" open><summary>运行停止与重放环境原因</summary><pre>'
            + dump(report["execution_issues"])
            + "</pre></details>"
        )
    if report.get("ci_gates"):
        sections += (
            '<details class="section" open><summary>严格 CI gate（与 CLI 相同）</summary><pre>'
            + dump(report["ci_gates"])
            + "</pre></details>"
        )
    if "actors" in report:
        sections += (
            '<details class="section"><summary>E7 角色策略与模型调用审计</summary><pre>'
            + dump(report["actors"])
            + "</pre></details>"
        )
    distribution = " · ".join(f"{esc(key)} {value}" for key, value in report["distribution"].items())
    result = (
        """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>E4 示例证据报告</title><style>
    *{box-sizing:border-box}body{font:16px/1.65 system-ui;margin:24px auto;padding:0 24px;max-width:1400px;color:#17212c;overflow-wrap:anywhere}h1,h2{line-height:1.3}h1{font-size:30px}h2{font-size:22px;margin-top:28px}.summary{background:#f1f5f9;border-left:4px solid #355880;padding:12px 16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:16px;font-size:13px}table{border-collapse:collapse;table-layout:fixed;min-width:1060px;width:100%;font-size:14px}th:nth-child(1){width:130px}th:nth-child(2){width:175px}th:nth-child(3){width:130px}th:nth-child(4){width:390px}td,th{border:1px solid #d7dee5;padding:10px;text-align:left;vertical-align:top}th{background:#eef2f6}td:first-child{white-space:nowrap}details{padding:10px 0;border-bottom:1px solid #d7dee5}summary{cursor:pointer}details.section>summary{font-weight:650}.table{overflow-x:auto}a{color:#174b9b;display:inline-block;margin-right:6px}.fail{color:#9f1722;font-weight:700}.inconclusive{color:#805a0d;font-weight:700}.pass{color:#186343}.not_applicable{color:#536577}@media(max-width:600px){body{padding:0 16px;margin:16px auto}h1{font-size:25px}}
    </style></head><body><h1>E4 示例证据报告</h1>"""
        + f'<p>生命周期：{esc(report["status"])} · 所选范围：<strong>{esc(report["verdict"])}</strong><br>run：{esc(report["run_id"])}</p><div class="summary">示例系统；无真实资金与客户验证。refund_core_20 gate：{esc(report["gate"]["verdict"])}<br>{distribution}<br>当前去重 Finding：{len(report["findings"])} · 业务通过与严格 CI gate 分别列示；平台工程验收见交付检查表</div><h2>四态检查</h2><p>失败与证据不足优先展示。证据编号可跳转查看原始观测；窄屏可横向滚动表格。</p><div class="table"><table><thead><tr><th>规则</th><th>对象</th><th>结论</th><th>原因</th><th>证据引用</th></tr></thead><tbody>'
        + rows
        + "</tbody></table></div><h2>范围、发现与限制</h2>"
        + sections
        + "<h2>原始观测（脱敏，保留所有冲突）</h2>"
        + evidence
        + "</body></html>"
    )

    if report["scope"]["phase"] in {"E5", "E6", "E7"}:
        result = result.replace("E4 示例证据报告", "E5 示例证据报告").replace(
            "S11—S20 与 E5—E10 未完成", "E6—E10 未实施"
        )
    if report["scope"]["phase"] == "E6":
        result = result.replace("E5 示例证据报告", "E6 示例证据报告").replace(
            "E6—E10 未实施", "E7—E10 未实施"
        )
    if report["scope"]["phase"] == "E7":
        result = result.replace("E5 示例证据报告", "E7 示例证据报告").replace(
            "E6—E10 未实施", "E8—E10 未实施；未证明 AI 增量"
        )
    return result
