"""E10 counterexamples for incomplete execution and shared CI gate classification."""

from uuid import uuid4

import pytest

from packages.evaluators.gates import gate_result
from packages.transport.security import Scope, digest


@pytest.mark.parametrize(
    "reason", ["budget_exhausted", "concurrency_budget_exhausted", "model_budget_exhausted"]
)
@pytest.mark.parametrize("observed_defect", [False, True])
def test_unfinished_budget_is_exit_three_even_with_observed_counterexample(reason, observed_defect):
    report = {
        "status": "failed",
        "stop_reason": reason,
        "verdict": "inconclusive",
        "checks": [{"verdict": "fail", "attribution": "product_defect"}] if observed_defect else [],
        "selected_gate": {"verdict": "inconclusive"},
        "gate": {"verdict": "inconclusive"},
    }
    for selection in ("selected", "suite"):
        actual = gate_result(report, selection)
        assert actual["exit_code"] == 3, actual
        assert actual["verdict"] == "inconclusive"


def test_missing_fixture_is_incomplete_evidence_not_infrastructure_error():
    result = gate_result({"status": "failed", "stop_reason": "fixture_mismatch", "checks": []})
    assert result["exit_code"] == 3, result
    assert result["verdict"] == "inconclusive"


def test_fixture_failure_has_separate_redacted_environment_cause_in_json_and_html(monkeypatch):
    from packages.evaluators.reporting import render_html
    from packages.simulator import replay

    scope = Scope(project_id=uuid4(), run_id=uuid4())
    assets = {kind: {"payload": [], "content_hash": digest([])} for kind in ("actors", "faults", "snapshot")}
    manifest = {
        "assets": {kind: {"content_hash": digest([])} for kind in assets},
        "target_product_version": "fixed",
        "versions": {"put": {"content_hash": "test-build"}},
        "mode": "input",
    }
    row = {"payload": manifest, "content_hash": digest(manifest)}
    monkeypatch.setattr(replay, "bundle", lambda *_: ({}, row, None, assets, {}))
    report = {
        "status": "failed",
        "stop_reason": "fixture_mismatch",
        "run_id": str(scope.run_id),
        "verdict": "inconclusive",
        "runtime": {
            "journal": [
                {
                    "sequence": 17,
                    "kind": "fixture_mismatch",
                    "payload": {
                        "reason": "missing_required_actor_fixture",
                        "attribution": "environment_error",
                        "details": {"authorization": "synthetic-canary-must-be-redacted"},
                    },
                }
            ]
        },
        "scope": {},
        "versions": {},
        "selected_gate": {},
        "gate": {},
        "distribution": {},
        **{
            key: []
            for key in (
                "observations",
                "checks",
                "findings",
                "unverified",
                "rules",
                "coverage",
                "access_checks",
                "observation_conflicts",
                "evidence_issues",
                "observation_window",
                "budget",
            )
        },
    }
    result = replay.replay_report(None, scope, report)
    issue = result["execution_issues"][0]
    assert issue["attribution"] == "environment_error"
    assert issue["reason"] == "missing_required_actor_fixture"
    assert issue["evidence_refs"] == [f"private://postgres/{scope.namespace}/runtime_journal/17"]
    assert issue["details"]["authorization"] == "[REDACTED]"
    rendered = render_html(result)
    assert "运行停止与重放环境原因" in rendered
    assert issue["reason"] in rendered and issue["evidence_refs"][0] in rendered
