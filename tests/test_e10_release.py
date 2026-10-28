"""E10 regression for one authoritative comparison gate and version provenance."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from packages.simctl.main import execute
from packages.transport.security import Scope


@pytest.mark.parametrize("code,repair", [(0, True), (1, False), (2, False), (3, True), (3, False)])
def test_cli_compare_uses_api_gate_without_second_result_read(code, repair, monkeypatch):
    gate = {
        "exit_code": code,
        "reasons": [],
        "verdict": {0: "pass", 1: "fail", 2: "error", 3: "inconclusive"}[code],
    }
    comparison = {
        "repair_verified": repair,
        "ci_gates": {"selected": gate},
        "target_ci_gates": {"selected": gate},
    }

    class Client:
        def __init__(self, args):
            pass

        def request(self, method, path, **kwargs):
            assert (method, path) == ("GET", "runs/source/compare"), (
                "must not combine separate report snapshots"
            )
            return comparison

    args = SimpleNamespace(
        command="compare", source="source", target="target", project="project", gate="selected"
    )
    monkeypatch.setattr("packages.simctl.main.Client", Client)
    status, output = execute(args)
    assert status == code
    assert output["comparison"]["ci_gates"]["selected"] == gate


def test_evaluator_version_matches_manifest_provenance():
    from packages.evaluators.refund import Policy
    from packages.transport.build import provenance

    assert provenance()["rules"]["version"] == "refund-v" + Policy(200000, 1).version


@pytest.mark.parametrize("drift", ["none", "build", "policy", "missing_build"])
def test_comparison_detects_current_rules_drift_from_frozen_target(monkeypatch, drift):
    from packages.evaluators import comparison

    source = Scope(project_id=uuid4(), run_id=uuid4())
    target = Scope(project_id=source.project_id, run_id=uuid4())
    frozen_build = {"version": "refund-v1", "content_hash": "old-rules"}
    gates = {name: {"exit_code": 0, "verdict": "pass", "reasons": []} for name in ("selected", "suite")}
    reports = {}
    manifests = {}
    for scope, version, verdict in [(source, "buggy", "fail"), (target, "fixed", "pass")]:
        reports[scope.run_id] = {
            "run_id": str(scope.run_id),
            "verdict": verdict,
            "status": "completed",
            "checks": [{"rule_id": "REFUND_001", "object_id": "r", "verdict": verdict, "evidence_refs": []}],
            "versions": {"evaluator_build": frozen_build, "rule_version": "1", "rules_hash": "policy-1"},
            "ci_gates": gates,
            "replay": {"issues": [], "input_deviations": []},
        }
        manifests[scope.run_id] = {
            "versions": {"rules": frozen_build},
            "target_product_version": version,
            "assets": {"actors": {"content_hash": "same-inputs"}},
        }
    frozen_history = deepcopy(reports)
    current = deepcopy(reports[target.run_id])
    if drift == "build":
        current["versions"]["evaluator_build"] = {"version": "refund-v2", "content_hash": "new-rules"}
    elif drift == "policy":
        current["versions"].update(rule_version="2", rules_hash="policy-2")
    elif drift == "missing_build":
        current["versions"].pop("evaluator_build")

    def bundle(_db, scope, require_seal=False):
        return (
            {},
            {"payload": manifests[scope.run_id], "content_hash": "manifest-" + str(scope.run_id)},
            {"payload": {"report": reports[scope.run_id]}},
            {},
            {},
        )

    def evidence(report):
        identity = report["run_id"]
        return {
            "put_business_calls": 1,
            "put_versions": ["fixed" if identity == str(target.run_id) else "buggy"],
            "observation_ids": ["observation-" + identity],
            "ledger_entry_ids": ["ledger-" + identity],
            "webhook_event_ids": ["webhook-" + identity],
            "provider_calls_by_command": {"r": 1},
        }

    monkeypatch.setattr(comparison, "bundle", bundle)
    monkeypatch.setattr(comparison, "integrity", lambda *_: [])
    monkeypatch.setattr(comparison, "axes", lambda manifest: {"PUT": manifest["target_product_version"]})
    monkeypatch.setattr(comparison, "evidence_summary", evidence)
    monkeypatch.setattr("packages.evaluators.reporting.report", lambda *_: current)
    result = comparison.compare_runs(None, source, target)
    assert result["repair_verified"] is (drift == "none"), result["confounders"]
    assert result["direct_put_comparison"] is (drift == "none")
    assert result["ci_gates"]["selected"]["exit_code"] == (0 if drift == "none" else 3)
    assert reports == frozen_history  # No rewriting source or target historical seals.
