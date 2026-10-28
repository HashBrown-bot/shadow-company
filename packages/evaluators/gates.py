"""One gate policy for API, CLI and CI. It never changes evaluator business facts."""

REQUIRED = {"REFUND_001", "REFUND_002", "APPROVAL_001"}
UNFINISHED = {
    "cancelled",
    "budget_exhausted",
    "concurrency_budget_exhausted",
    "model_budget_exhausted",
    "fixture_mismatch",
    "reset",
    "reset_incomplete",
    "remote_outcome_unknown",
    "remote_outcome_unknown_legacy_scope",
    "emergency_stop",
}


def gate_result(report, selection="selected", required=None):
    required = REQUIRED | set(required or [])
    reasons = []
    checks = report.get("checks", [])
    gate = report.get("selected_gate" if selection == "selected" else "gate", {})
    code = 3
    stop = report.get("stop_reason")
    # An unfinished run stays incomplete even when a counterexample already exists.
    if report.get("status") in {"queued", "running", "cancelled"} or stop in UNFINISHED:
        reasons.append("运行未完成、取消、预算耗尽、必需重放输入缺失/偏离或证据已清理")
    elif report.get("status") == "failed":
        code = 2
        reasons.append("配置、适配器或基础设施执行错误")
    elif any(c.get("verdict") == "fail" and c.get("attribution") == "product_defect" for c in checks):
        code = 1
        reasons.append("独立证据确认业务规则失败")
    else:
        if gate.get("verdict") != "pass":
            reasons.append("所选场景或套件未完成必要覆盖")
        for rule in sorted(required):
            applicable = [
                c for c in checks if c.get("rule_id") == rule and c.get("verdict") != "not_applicable"
            ]
            if not applicable or any(
                c.get("verdict") != "pass" or not c.get("evidence_refs") for c in applicable
            ):
                reasons.append(f"必需检查 {rule} 未获得完整通过证据；不适用不能替代")
        if any(c.get("verdict") == "not_applicable" and not c.get("reason") for c in checks):
            reasons.append("不适用检查缺少契约理由")
        if report.get("evidence_issues"):
            reasons.append("存在证据问题")
        if not reasons:
            code = 0
    return {
        "schema_version": "e10-gate-2",
        "selection": selection,
        "strict": True,
        "required_checks": sorted(required),
        "exit_code": code,
        "verdict": {0: "pass", 1: "fail", 2: "error", 3: "inconclusive"}[code],
        "reasons": reasons,
    }
