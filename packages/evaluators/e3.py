"""Narrow S01/S02 evidence correlation, not the E4 ruleset or full-suite gate.

Inputs are frozen expectations plus source-labelled observations. No PUT behavior selector.
"""

from packages.transport.security import digest


def evaluate(expected, observations, scope):
    checks = []
    for wanted in expected:
        refs = []
        entries = None
        product = None
        callbacks = []
        for obs in observations:
            payload = obs["payload"]
            if not isinstance(payload, dict):
                continue
            response = payload.get("response", {})
            if not isinstance(response, dict):
                response = {}
            if (
                obs["source"] == "provider_ledger"
                and obs["evidence_kind"] == "dependency_evidence"
                and response.get("status") == 200
            ):
                body = response.get("body", {})
                if (
                    isinstance(body, dict)
                    and isinstance(body.get("entries"), list)
                    and all(isinstance(entry, dict) for entry in body["entries"])
                    and body.get("complete") is True
                    and body.get("project_id") == str(scope.project_id)
                    and body.get("run_id") == str(scope.run_id)
                ):
                    entries = [
                        e
                        for e in body.get("entries", [])
                        if e.get("refund_command_id") == wanted["refund_command_id"]
                    ]
                    refs.append(str(obs["observation_id"]))
            if (
                obs["source"] == "put"
                and obs["evidence_kind"] == "product_observation"
                and payload.get("request", {}).get("method") == "GET"
                and payload.get("request", {}).get("path") == "/refunds/" + wanted["refund_command_id"]
                and response.get("status") == 200
            ):
                product = response.get("body") if isinstance(response.get("body"), dict) else None
                refs.append(str(obs["observation_id"]))
            if (
                obs["source"] == "provider_webhook"
                and obs["evidence_kind"] == "dependency_evidence"
                and payload.get("refund_command_id") == wanted["refund_command_id"]
            ):
                callbacks.append(payload)
                refs.append(str(obs["observation_id"]))
        verdict = "inconclusive"
        reason = "缺少完整独立账本、产品查询或已验签回调"
        ledger_refs = []
        if entries is not None and product is not None and callbacks:
            successes = [e for e in entries if e.get("status") == "succeeded"]
            ledger_refs = [e.get("entry_id") for e in successes]
            correct = (
                len(successes) == 1
                and type(successes[0].get("amount_minor")) is int
                and all(successes[0].get(k) == wanted[k] for k in ["payment_id", "amount_minor", "currency"])
            )
            if correct:
                entry = successes[0]
                correct = (
                    correct
                    and entry.get("recipient") == "sha256:" + digest(wanted["recipient"])
                    and product.get("recipient") == entry.get("recipient")
                )
                correct = (
                    correct
                    and entry.get("project_id") == str(scope.project_id)
                    and entry.get("run_id") == str(scope.run_id)
                    and product.get("project_id") == str(scope.project_id)
                    and product.get("run_id") == str(scope.run_id)
                    and product.get("refund_id") == wanted["refund_command_id"]
                    and product.get("provider_entry_id") == entry["entry_id"]
                    and product.get("status") == "succeeded"
                    and type(product.get("amount_minor")) is int
                    and all(product.get(k) == wanted[k] for k in ["payment_id", "amount_minor", "currency"])
                    and any(
                        cb.get("entry_id") == entry["entry_id"]
                        and cb.get("status") == "succeeded"
                        and type(cb.get("amount_minor")) is int
                        and cb.get("project_id") == str(scope.project_id)
                        and cb.get("run_id") == str(scope.run_id)
                        and all(cb.get(k) == wanted[k] for k in ["amount_minor", "currency", "payment_id"])
                        for cb in callbacks
                    )
                )
                if wanted["approval_required"]:
                    approval = product.get("approval") if isinstance(product.get("approval"), dict) else {}
                    correct = (
                        correct
                        and type(product.get("version")) is int
                        and type(approval.get("version")) is int
                        and approval.get("approved") is True
                        and approval.get("approved_by") == "approver"
                        and all(
                            approval.get(k) == product.get(k)
                            for k in ["refund_id", "amount_minor", "currency", "recipient", "version"]
                        )
                    )
            verdict = "pass" if correct else "fail"
            reason = "独立账本、签名回调与 PUT 查询一致" if correct else "观测与冻结的场景要求不一致"
        checks.append(
            {
                "scenario_id": wanted["scenario_id"],
                "object_id": wanted["refund_command_id"],
                "verdict": verdict,
                "reason": reason,
                "evidence_refs": refs,
                "provider_entry_ids": ledger_refs,
            }
        )
    overall = (
        "fail"
        if any(c["verdict"] == "fail" for c in checks)
        else ("pass" if checks and all(c["verdict"] == "pass" for c in checks) else "inconclusive")
    )
    return {"verdict": overall, "checks": checks}
