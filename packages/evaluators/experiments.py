"""Paired experiment measurements. Root-cause independence requires explicit human review."""

import html
import json

from fastapi import HTTPException
from sqlalchemy import text

from packages.evaluators.comparison import axes, integrity
from packages.evaluators.reporting import report
from packages.simulator.replay import bundle
from packages.transport.security import Scope, digest


def experiment_report(db, project_id, experiment_id):
    with db.connect() as c:
        experiment = (
            c.execute(
                text("SELECT * FROM experiments WHERE project_id=:p AND experiment_id=:e"),
                {"p": project_id, "e": experiment_id},
            )
            .mappings()
            .first()
        )
        if experiment is None:
            raise HTTPException(404, "实验不存在")
        members = (
            c.execute(
                text(
                    "SELECT * FROM experiment_runs WHERE project_id=:p AND experiment_id=:e ORDER BY seed,mode"
                ),
                {"p": project_id, "e": experiment_id},
            )
            .mappings()
            .all()
        )
        reviews = (
            c.execute(
                text("""SELECT f.* FROM finding_reviews f JOIN experiment_runs e USING(project_id,run_id)
            WHERE e.project_id=:p AND e.experiment_id=:e"""),
                {"p": project_id, "e": experiment_id},
            )
            .mappings()
            .all()
        )
    all_reviews = {(str(r["run_id"]), str(r["finding_id"])): r for r in reviews}
    outcomes, reports, problems = [], {}, []
    if digest(experiment["payload"]) != experiment["content_hash"]:
        problems.append("experiment_request_hash_mismatch")
    for member in members:
        run_id, mode, seed = str(member["run_id"]), member["mode"], member["seed"]
        try:
            scope = Scope(project_id=project_id, run_id=run_id)
            current = report(db, scope)
            if current["status"] in {"completed", "failed", "cancelled"}:
                _, row, seal, assets, _ = bundle(db, scope, require_seal=True)
                problems.extend(f"{seed}:{mode}:{issue}" for issue in integrity(db, scope, row, seal, assets))
        except HTTPException:
            current = {
                "status": "unavailable",
                "verdict": "inconclusive",
                "findings": [],
                "unverified": ["run_evidence_unavailable"],
            }
        reports[(seed, mode)] = current
        outcomes.append(
            {
                "run_id": run_id,
                "mode": mode,
                "seed": seed,
                "status": current["status"],
                "verdict": current["verdict"],
                "unverified": current["unverified"],
                "model_calls": current.get("budget", {}).get("cost", {}).get("model_calls"),
            }
        )
    for seed in experiment["payload"]["seeds"]:
        left, right = reports.get((seed, "rule")), reports.get((seed, "hybrid"))
        if not left or not right or any("actors" not in r for r in (left, right)):
            problems.append(f"{seed}:missing_pair_or_evidence")
            continue
        a, b = axes(left["replay"]["manifest"]), axes(right["replay"]["manifest"])
        # Strategy is the independent variable. Every other condition must match exactly.
        a.pop("actor_policy"), b.pop("actor_policy")
        for key in a:
            if a[key] != b[key]:
                problems.append(f"{seed}:changed_{key}")
        if left["actors"]["policy"]["budget"] != right["actors"]["policy"]["budget"]:
            problems.append(f"{seed}:changed_model_budget")
        for mode, item in (("rule", left), ("hybrid", right)):
            if (
                item["status"] != "completed"
                or item["replay"]["issues"]
                or item["actors"]["issues"]
                or item["selected_gate"]["verdict"] == "inconclusive"
            ):
                problems.append(f"{seed}:{mode}:incomplete")
    metrics = {}
    for mode in ("rule", "hybrid"):
        selected = [o for o in outcomes if o["mode"] == mode]
        roots, reviewed, seconds, candidates = set(), [], [], 0
        calls, tokens, measured = 0, 0, True
        for item in selected:
            r = reports[(item["seed"], mode)]
            measured = measured and "actors" in r and not r["actors"]["issues"]
            calls += r.get("budget", {}).get("cost", {}).get("model_calls", 0)
            tokens += r.get("budget", {}).get("cost", {}).get("model_tokens", 0)
            for f in r["findings"]:
                if f["attribution"] != "product_defect":
                    continue
                candidates += 1
                review = all_reviews.get((item["run_id"], str(f["finding_id"])))
                if review is None:
                    continue
                if (
                    digest(review["payload"]) != review["content_hash"]
                    or review["payload"]["evidence_hash"] != r["evidence_hash"]
                ):
                    problems.append("review_evidence_changed")
                    continue
                v = review["payload"]
                reviewed.append(v)
                if v["decision"] == "confirmed":
                    roots.add(v["root_cause_id"])
                if v["human_seconds"] is not None:
                    seconds.append(v["human_seconds"])
        metrics[mode] = {
            "observed_product_findings": candidates,
            "confirmed_independent_defects": len(roots) if reviewed else None,
            "confirmed_root_cause_groups": sorted(roots),
            "false_positives": sum(v["decision"] == "false_positive" for v in reviewed) if reviewed else None,
            "human_confirmation_seconds": sum(seconds) if seconds else None,
            "timed_reviews": len(seconds),
            "reviewed_findings": len(reviewed),
            "unreviewed_findings": candidates - len(reviewed),
            "review_measurement": "未测"
            if not reviewed
            else "已测"
            if len(reviewed) == candidates
            else "部分已测",
            "model_calls": calls if measured else None,
            "model_tokens": tokens if measured else None,
            "estimated_model_cost_microusd": 0 if measured and calls == 0 else None,
            "cost_source": "no_model_calls_no_model_fee"
            if measured and calls == 0
            else "未测：需真实服务用量及带日期的单价来源",
            "infrastructure_cost": None,
        }
    expected = len(experiment["payload"]["seeds"]) * 2
    if len(members) != expected:
        problems.append("pair_creation_incomplete")
    return {
        "schema_version": "e7-experiment-1",
        "project_id": str(project_id),
        "experiment_id": str(experiment_id),
        "request": experiment["payload"],
        "request_hash": experiment["content_hash"],
        "paired_conditions_verified": not problems,
        "comparison_issues": sorted(set(problems)),
        "runs": outcomes,
        "metrics": metrics,
        "model_service_test": "not_run",
        "protocol_test_results_are_separate": True,
        "natural_language_scenarios": "not_applicable: ordinary API PUT has no language entry",
        "ai_increment_proven": False,
        "conclusion": "未执行真实模型实验，未证明 AI 增量；本次核验普通 API 的规则回退及配对运行",
        "limitations": [
            "人工独立根因、误报和确认耗时未采集时为 null/未测；Finding 数不等于独立缺陷数",
            "两个策略使用相同产品、契约、环境、seed 集、快照、调度与预算；条件缺失或变化时不可比较",
            "无真实客户、市场预测或满意度指标；E9—E10 未完成",
        ],
    }


def render_experiment(result):
    def esc(value):
        return html.escape(str(value), quote=True)

    rows = "".join(
        "<tr><td>"
        + "</td><td>".join(
            esc(x)
            for x in (
                mode,
                value["observed_product_findings"],
                value["confirmed_independent_defects"]
                if value["confirmed_independent_defects"] is not None
                else "未测",
                value["false_positives"] if value["false_positives"] is not None else "未测",
                value["human_confirmation_seconds"]
                if value["human_confirmation_seconds"] is not None
                else "未测",
                value["model_calls"],
                value["estimated_model_cost_microusd"],
                value["cost_source"],
            )
        )
        + "</td></tr>"
        for mode, value in result["metrics"].items()
    )
    return (
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>E7 规则与混合角色对照</title><style>body{font:16px/1.6 system-ui;max-width:1100px;margin:24px auto;padding:16px}table{border-collapse:collapse;min-width:900px}td,th{border:1px solid #ccc;padding:8px;text-align:left}.table{overflow-x:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style>
    <h1>E7 规则与混合角色对照</h1><p>本机示例 · 无真实资金、客户或市场预测</p>"""
        + "<p>"
        + esc(result["conclusion"])
        + "</p><p>配对条件核验："
        + esc(result["paired_conditions_verified"])
        + "</p><div class=table><table><tr><th>策略</th><th>规则发现</th><th>确认独立缺陷</th><th>误报</th><th>人工秒数</th><th>调用量</th><th>费用（微美元）</th><th>估算来源</th></tr>"
        + rows
        + "</table></div><details><summary>完整条件、未验证范围与证据</summary><pre>"
        + esc(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        + "</pre></details></html>"
    )
