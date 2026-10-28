"""Compare evidence-backed outcomes; separate PUT changes from changed test conditions."""

import html
import json

from sqlalchemy import text

from packages.simulator.replay import BOUNDARY, LIMITS, bundle, check_assets, evidence_summary
from packages.transport.security import digest


def axes(manifest):
    versions = manifest["versions"]
    return {
        "PUT": {"version": manifest["target_product_version"], "build": versions["put"]["content_hash"]},
        "contract_semantics": manifest["contract_semantics_hash"],
        "rules": {"config": manifest["rules"]["content_hash"], "code": versions["rules"]["content_hash"]},
        "environment": manifest["environment"],
        "provider": versions["provider"],
        "adapter": versions["adapter"],
        "platform_code": versions["platform"],
        "dependencies": versions["dependencies"],
        "postgres_version": manifest["postgres_version"],
        "seed": manifest["seed"],
        "runtime_budget_and_time": manifest["runtime"],
        "initial_snapshot": manifest["snapshot_hash"],
        "role_fixtures": manifest["assets"]["actors"]["content_hash"],
        "fault_plan": manifest["assets"]["faults"]["content_hash"],
        "planned_input_schedule": manifest["planned_input_schedule_hash"],
        "control_boundary": manifest["control_boundary"],
        "actor_policy": manifest.get("actor_policy"),
    }


def integrity(db, scope, row, seal, assets):
    problems = check_assets(row["payload"], assets)
    if (
        digest(row["payload"]) != row["content_hash"]
        or digest(seal["payload"]) != seal["content_hash"]
        or seal["parent_hash"] != row["content_hash"]
    ):
        problems.append("manifest_or_seal_hash_mismatch")
    saved = seal["payload"]["report"]["observations"]
    with db.connect() as c:
        current = [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT observation_id,digest,payload FROM observations WHERE project_id=:p AND run_id=:r"
                ),
                scope.params,
            ).mappings()
        ]
    if {str(o["observation_id"]): o["digest"] for o in current} != {
        str(o["observation_id"]): o["digest"] for o in saved
    } or any(digest(o["payload"]) != o["digest"] for o in current):
        problems.append("evidence_changed_since_seal")
    return problems


def compare_runs(db, source, target):
    from packages.evaluators.reporting import report

    _, left, left_seal, left_assets, _ = bundle(db, source, require_seal=True)
    # Re-evaluate target completeness. Stored trace cannot supply the target outcome.
    current = report(db, target)
    _, right, right_seal, right_assets, _ = bundle(db, target, require_seal=True)
    baseline = left_seal["payload"]["report"]
    a, b = axes(left["payload"]), axes(right["payload"])
    changes = [{"dimension": k, "changed": a[k] != b[k], "source": a[k], "target": b[k]} for k in a]
    # A target is re-evaluated by today's process. Two matching historical Manifests
    # cannot prove that this new evaluation used the same rules as their sealed runs.
    frozen_build = right["payload"]["versions"]["rules"]
    current_build = current["versions"].get("evaluator_build")
    sealed_versions = right_seal["payload"]["report"].get("versions", {})
    sealed_policy = {key: sealed_versions.get(key) for key in ("rule_version", "rules_hash")}
    current_policy = {key: current["versions"].get(key) for key in ("rule_version", "rules_hash")}
    changes.extend(
        [
            {
                "dimension": "target_evaluator_since_manifest",
                "changed": current_build != frozen_build,
                "source": frozen_build,
                "target": current_build,
            },
            {
                "dimension": "target_evaluation_since_seal",
                "changed": current_policy != sealed_policy,
                "source": sealed_policy,
                "target": current_policy,
            },
        ]
    )
    confounders = [c["dimension"] for c in changes if c["changed"] and c["dimension"] != "PUT"]
    issues = {
        "source": integrity(db, source, left, left_seal, left_assets),
        "target": integrity(db, target, right, right_seal, right_assets),
    }
    before, after = evidence_summary(baseline), evidence_summary(current)
    fresh = (
        source.run_id != target.run_id
        and after["put_business_calls"] > 0
        and after["put_versions"] == [right["payload"]["target_product_version"]]
        and not set(before["observation_ids"]) & set(after["observation_ids"])
        and not set(before["ledger_entry_ids"]) & set(after["ledger_entry_ids"])
        and not set(before["webhook_event_ids"]) & set(after["webhook_event_ids"])
    )
    rows = []
    old_checks = {(c["rule_id"], c["object_id"]): c for c in baseline["checks"]}
    new_checks = {(c["rule_id"], c["object_id"]): c for c in current["checks"]}
    for key in sorted(set(old_checks) | set(new_checks)):
        old, new = old_checks.get(key), new_checks.get(key)
        rows.append(
            {
                "rule_id": key[0],
                "object_id": key[1],
                "source": old and old["verdict"],
                "target": new and new["verdict"],
                "source_evidence": old["evidence_refs"] if old else [],
                "target_evidence": new["evidence_refs"] if new else [],
                "comparable": bool(old and new) and not confounders,
            }
        )
    paths = []
    for rid in sorted(set(before["provider_calls_by_command"]) | set(after["provider_calls_by_command"])):
        x, y = before["provider_calls_by_command"].get(rid, 0), after["provider_calls_by_command"].get(rid, 0)
        if x != y:
            paths.append(
                {
                    "object_id": rid,
                    "boundary": "PUT_to_provider",
                    "expected_path_calls": x,
                    "actual_path_calls": y,
                    "classification": "allowed_product_path_change",
                    "explanation": "新版本可减少重试或改为查询对账；调用次数差异本身不判产品错误，资金结论仍由新证据产生",
                }
            )
    replay_issues = current["replay"]["issues"]
    comparable = not confounders and not any(issues.values()) and not replay_issues and fresh
    fixed = (
        comparable
        and baseline["verdict"] == "fail"
        and current["verdict"] == "pass"
        and current["status"] == "completed"
        and all(not (c["source"] == "fail" and c["target"] != "pass") for c in rows)
    )
    comparison_gates = {}
    for selection, gate in current["ci_gates"].items():
        code = gate["exit_code"] or (0 if fixed else 3)
        comparison_gates[selection] = {
            **gate,
            "schema_version": "e10-compare-gate-1",
            "exit_code": code,
            "verdict": {0: "pass", 1: "fail", 2: "error", 3: "inconclusive"}[code],
            "reasons": gate["reasons"] + ([] if fixed else ["尚未验证声明范围内的修复"]),
        }
    return {
        "schema_version": "e6-compare-1",
        "project_id": str(source.project_id),
        "source_run_id": str(source.run_id),
        "target_run_id": str(target.run_id),
        "source_manifest_hash": left["content_hash"],
        "target_manifest_hash": right["content_hash"],
        "source_verdict": baseline["verdict"],
        "target_verdict": current["verdict"],
        "repair_verified": fixed,
        "ci_gates": comparison_gates,
        "target_ci_gates": current["ci_gates"],
        "conclusion": "repair_verified_in_declared_scope" if fixed else "not_a_verified_repair",
        "direct_put_comparison": comparable,
        "changes": changes,
        "confounders": confounders,
        "fresh_target_calls_and_evidence": fresh,
        "evidence": {"source": before, "target": after},
        "integrity_issues": issues,
        "replay_issues": replay_issues,
        "checks": rows,
        "expected_path": before["provider_calls_by_command"],
        "actual_path": after["provider_calls_by_command"],
        "path_deviations": paths,
        "input_deviations": current["replay"]["input_deviations"],
        "exact_actor_inputs": left["payload"]["assets"]["actors"]["content_hash"]
        == right["payload"]["assets"]["actors"]["content_hash"]
        and not current["replay"]["input_deviations"],
        "non_comparable": BOUNDARY["uncontrolled"] + confounders,
        "control_boundary": BOUNDARY,
        "limits": LIMITS,
    }


def render_compare(result):
    def esc(value):
        return html.escape(str(value), quote=True)

    rows = "".join(
        f"<tr><td>{esc(c['dimension'])}</td><td>{'变化' if c['changed'] else '相同'}</td></tr>"
        for c in result["changes"]
    )
    sections = "".join(
        f"<details><summary>{title}</summary><pre>{esc(json.dumps(result[key], ensure_ascii=False, indent=2, default=str))}</pre></details>"
        for title, key in [
            ("严格比较 CI gate（与 CLI 相同）", "ci_gates"),
            ("目标运行 CI gate", "target_ci_gates"),
            ("路径偏离与合法重试变化", "path_deviations"),
            ("角色输入偏离", "input_deviations"),
            ("不可比较范围", "non_comparable"),
            ("控制边界", "control_boundary"),
            ("新调用与独立证据", "evidence"),
            ("逐规则比较", "checks"),
            ("完整性问题", "integrity_issues"),
            ("fixture 问题", "replay_issues"),
            ("限制", "limits"),
        ]
    )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>E6 运行比较</title><style>body{font:16px/1.6 system-ui;max-width:1000px;margin:24px auto;padding:0 20px;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #cbd5e1;text-align:left}pre{white-space:pre-wrap;font-size:13px;background:#f1f5f9;padding:12px}summary{cursor:pointer;padding:12px 0}strong{color:#174b71}</style><h1>E6 运行比较</h1>'
        + f"<p>示例系统 · {esc(result['source_run_id'])} → {esc(result['target_run_id'])}</p><p>旧结论 {esc(result['source_verdict'])} → 新结论 {esc(result['target_verdict'])}</p><p><strong>{'已在声明范围验证修复' if result['repair_verified'] else '尚未验证修复'}</strong></p><p>history 只读历史；input 实际调用目标版本；controlled 仅控制声明的本机边界。不宣称任意 staging 完全确定性。</p><table><thead><tr><th>比较维度</th><th>变化</th></tr></thead><tbody>"
        + rows
        + "</tbody></table>"
        + sections
        + "</html>"
    )
