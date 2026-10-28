"""E6 real HTTP/Worker/PostgreSQL tests; repetitions keep independent evidence."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import text

from packages.transport.access import client_headers
from packages.transport.security import Scope, digest
from tests.test_e4_live import BASE
from tests.test_e5_live import config_for, save, wait_report


def setup_project(http, scenarios=("S12",), version="buggy"):
    response = http.post(BASE + "/api/projects", json={"name": "E6 本机重放验收 " + uuid4().hex})
    assert response.status_code == 201, response.text
    p = response.json()["id"]
    for v in ("buggy", "fixed"):
        add_contract(http, p, v, config_for(v))
    response = http.post(
        BASE + "/api/runs",
        json={
            "project_id": p,
            "contract_version": version,
            "idempotency_key": uuid4().hex,
            "suite_scope": "e6_core_20",
            "scenarios": list(scenarios),
        },
    )
    assert response.status_code == 202, response.text
    scope = Scope(project_id=p, run_id=response.json()["run_id"])
    result = wait_report(http, scope)
    assert result["status"] == "completed", (result["stop_reason"], result.get("replay"))
    return scope, result


def add_contract(http, p, name, config):
    response = http.put(BASE + f"/api/projects/{p}/contract", json={"version": name, "config": config})
    assert response.status_code == 200, response.text
    response = http.post(BASE + f"/api/projects/{p}/preflight", json={"contract_version": name})
    assert response.status_code == 200 and response.json()["passed"], response.text


def get(http, scope, suffix):
    response = http.get(
        BASE + f"/api/runs/{scope.run_id}/{suffix}", params={"project_id": str(scope.project_id)}
    )
    assert response.status_code == 200, response.text
    return response.json()


def replay(http, source, version="fixed", **options):
    request = {
        "project_id": str(source.project_id),
        "mode": "input",
        "target_contract_version": version,
        "target_product_version": version,
        "idempotency_key": uuid4().hex,
    } | options
    response = http.post(BASE + f"/api/runs/{source.run_id}/replay", json=request)
    assert response.status_code == 202, response.text
    target = Scope(project_id=source.project_id, run_id=response.json()["run_id"])
    return target, wait_report(http, target), request


def compare(http, source, target):
    response = http.get(
        BASE + f"/api/runs/{source.run_id}/compare",
        params={"project_id": str(source.project_id), "other_run_id": str(target.run_id)},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def e6_source(live_stack):
    source, report = setup_project(live_stack["http"])
    save("e6-source.json", report)
    assert report["verdict"] == "fail", report["replay"]["issues"]
    return source, report


def test_e6_input_fresh_calls_and_version_compare(live_stack, e6_source):
    source, original = e6_source
    http = live_stack["http"]
    before = get(http, source, "history")
    target, report, request = replay(http, source)
    save("e6-first-fixed-development.json", report)
    assert report["verdict"] == "pass", (report["stop_reason"], report["replay"]["issues"])
    comparison = compare(http, source, target)
    assert comparison["repair_verified"], comparison
    assert report["versions"]["evaluator_build"] == report["replay"]["manifest"]["versions"]["rules"]
    assert all(
        not change["changed"]
        for change in comparison["changes"]
        if change["dimension"] in {"target_evaluator_since_manifest", "target_evaluation_since_seal"}
    )
    assert comparison["exact_actor_inputs"] and comparison["direct_put_comparison"]
    assert comparison["path_deviations"][0]["classification"] == "allowed_product_path_change"
    assert comparison["evidence"]["source"]["provider_execution_calls"] == 2
    assert comparison["evidence"]["target"]["provider_execution_calls"] == 1
    assert comparison["evidence"]["target"]["put_versions"] == ["fixed"]
    assert comparison["evidence"]["target"]["put_business_calls"] >= 2
    assert get(http, source, "history") == before
    assert target.run_id != source.run_id
    assert original["checks"] != report["checks"]
    again = http.post(BASE + f"/api/runs/{source.run_id}/replay", json=request)
    assert again.status_code == 200 and again.json()["run_id"] == str(target.run_id)
    changed = http.post(BASE + f"/api/runs/{source.run_id}/replay", json=request | {"mode": "controlled"})
    assert changed.status_code == 409
    save(
        "e6-first-fixed.json",
        {"report": report, "compare": comparison, "manifest": get(http, target, "manifest")},
    )


def test_e6_twenty_consecutive_replays_no_hidden_failures(live_stack, e6_source):
    http = live_stack["http"]
    source, _ = e6_source
    before = get(http, source, "history")
    used_entries, used_callbacks, used_observations, runs = set(), set(), set(), []
    for version in ("buggy", "fixed"):
        for number in range(1, 11):
            target, report, _ = replay(http, source, version)
            comparison = compare(http, source, target)
            artifact = {
                "iteration": number,
                "target": version,
                "report": report,
                "compare": comparison,
                "manifest": get(http, target, "manifest"),
            }
            # Persist before asserting, so any failed repetition remains reviewable.
            save(f"e6-repeat-{version}-{number:02}.json", artifact)
            expected = "fail" if version == "buggy" else "pass"
            assert report["verdict"] == expected, (
                version,
                number,
                report["stop_reason"],
                report["replay"]["issues"],
            )
            assert report["status"] == "completed" and not report["replay"]["issues"]
            assert all(f["verified"] for f in report["runtime"]["faults"])
            assert comparison["direct_put_comparison"] and comparison["fresh_target_calls_and_evidence"]
            assert comparison["repair_verified"] is (version == "fixed")
            actual = comparison["evidence"]["target"]
            assert actual["put_versions"] == [version]
            assert actual["provider_execution_calls"] == (2 if version == "buggy" else 1)
            assert len(actual["ledger_entry_ids"]) == (2 if version == "buggy" else 1)
            assert actual["webhook_event_ids"] and actual["observation_ids"]
            for key, used in [
                ("ledger_entry_ids", used_entries),
                ("webhook_event_ids", used_callbacks),
                ("observation_ids", used_observations),
            ]:
                assert not used.intersection(actual[key])
                used.update(actual[key])
            runs.append(
                {
                    "version": version,
                    "iteration": number,
                    "run_id": str(target.run_id),
                    "verdict": report["verdict"],
                    "manifest_hash": report["replay"]["manifest_hash"],
                    "ledger_entry_ids": actual["ledger_entry_ids"],
                }
            )
    after = get(http, source, "history")
    assert before == after
    save(
        "e6-repetitions.json",
        {
            "runs": runs,
            "original_history_before_hash": digest(before),
            "original_history_after_hash": digest(after),
            "independent_runs": len({r["run_id"] for r in runs}),
            "scope": "local S12 commit_then_timeout; not arbitrary staging determinism",
        },
    )


def test_e6_history_zero_calls_and_no_database_mutation(live_stack, e6_source, monkeypatch):
    from fastapi.testclient import TestClient

    from packages.transport.http import SafeHTTP
    from services.api.main import create_app

    scope, _ = e6_source
    with live_stack["db"].connect() as c:
        before = {
            t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar()
            for t in (
                "jobs",
                "runs",
                "observations",
                "runtime_journal",
                "evaluations",
                "refund_put.audit",
                "payment_provider.audit",
            )
        }
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("history must never call any external service")

    monkeypatch.setattr(SafeHTTP, "request", forbidden)
    with TestClient(create_app(live_stack["db"]), headers=client_headers()) as client:
        response = client.post(
            f"/api/runs/{scope.run_id}/replay", json={"project_id": str(scope.project_id), "mode": "history"}
        )
        assert response.status_code == 200 and response.json()["calls_put"] is False
        assert (
            client.get(
                f"/api/runs/{scope.run_id}/history", params={"project_id": str(scope.project_id)}
            ).json()
            == response.json()
        )
    assert calls == []
    with live_stack["db"].connect() as c:
        assert before == {t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in before}


def test_e6_missing_required_fixture_is_not_product_failure(live_stack, e6_source):
    source, _ = e6_source
    http = live_stack["http"]
    actors = get(http, source, "manifest")["assets"]["actors"]["payload"]
    target, report, _ = replay(
        http, source, actor_fixtures=[f for f in actors if f["operation"] != "execute_refund"]
    )
    assert report["verdict"] == "inconclusive" and report["stop_reason"] == "fixture_mismatch"
    assert report["replay"]["fixture_mismatches"]
    assert not any(f["attribution"] == "product_defect" for f in report["findings"])
    assert report["replay"]["fresh_evidence"]["provider_execution_calls"] == 0
    assert report["execution_issues"][0]["attribution"] == "environment_error"
    assert report["execution_issues"][0]["reason"] == "missing_required_actor_fixture"
    assert report["execution_issues"][0]["evidence_refs"]
    assert report["ci_gates"]["selected"]["exit_code"] == 3
    assert report["ci_gates"]["suite"]["exit_code"] == 3
    rendered = http.get(
        BASE + f"/api/runs/{target.run_id}/report",
        params={"project_id": str(target.project_id), "format": "html"},
    )
    assert rendered.status_code == 200
    assert report["execution_issues"][0]["reason"] in rendered.text
    assert not compare(http, source, target)["repair_verified"]
    save("e6-missing-fixture.json", report)


def test_e6_wrong_prestate_cannot_be_blindly_delivered(live_stack, e6_source):
    source, _ = e6_source
    http = live_stack["http"]
    actors = deepcopy(get(http, source, "manifest")["assets"]["actors"]["payload"])
    next(f for f in actors if f["operation"] == "execute_refund")["precondition"]["fields"]["version"] = 99
    target, report, _ = replay(http, source, actor_fixtures=actors)
    assert report["verdict"] == "inconclusive" and report["stop_reason"] == "fixture_mismatch"
    assert report["replay"]["fresh_evidence"]["provider_execution_calls"] == 0
    mismatch = report["replay"]["fixture_mismatches"][0]["payload"]
    assert mismatch["reason"] == "precondition_mismatch_or_ambiguous_fixture"
    assert report["execution_issues"][0]["attribution"] == "environment_error"
    assert report["execution_issues"][0]["reason"] == mismatch["reason"]
    assert report["ci_gates"]["selected"]["exit_code"] == 3
    assert report["ci_gates"]["suite"]["exit_code"] == 3
    comparison = compare(http, source, target)
    assert not comparison["repair_verified"] and "role_fixtures" in comparison["confounders"]
    save("e6-prestate-mismatch.json", {"report": report, "compare": comparison})


def test_e6_reordered_fixture_storage_is_semantic_not_ordinal(live_stack, e6_source):
    source, _ = e6_source
    actors = get(live_stack["http"], source, "manifest")["assets"]["actors"]["payload"]
    _, report, _ = replay(live_stack["http"], source, actor_fixtures=list(reversed(actors)))
    assert report["verdict"] == "pass", report["replay"]["issues"]
    assert (
        report["replay"]["manifest"]["assets"]["actors"]["content_hash"]
        == get(live_stack["http"], source, "manifest")["planned"]["payload"]["assets"]["actors"][
            "content_hash"
        ]
    )


def test_e6_feedback_policy_deviation_visible_and_not_false_fix(live_stack):
    http = live_stack["http"]
    source, _ = setup_project(http, ("S05",))
    actors = get(http, source, "manifest")["assets"]["actors"]["payload"]
    for f in actors:
        if f["operation"] == "execute_refund":
            f["policy"] = "retry_if_unsettled_v1"
    target, report, _ = replay(http, source, actor_fixtures=actors)
    comparison = compare(http, source, target)
    assert report["replay"]["input_deviations"]
    assert any(d["payload"]["decision"] == "skip_settled" for d in report["replay"]["actor_decisions"])
    assert report["verdict"] == "inconclusive"  # S05 intentionally requires the second call.
    assert not comparison["exact_actor_inputs"] and not comparison["repair_verified"]
    save("e6-feedback-deviation.json", {"report": report, "compare": comparison})


@pytest.mark.parametrize("dimension", ["environment", "rules"])
def test_e6_rule_or_environment_changes_not_attributed_to_put(live_stack, e6_source, dimension):
    http = live_stack["http"]
    source, _ = e6_source
    config = config_for("fixed")
    if dimension == "environment":
        config["environment"]["version"] = "0.2.1"
    else:
        next(r for r in config["rules"] if r["id"] == "TIME_001")["params"]["observation_wall_seconds"] = 2
    name = dimension + "-changed"
    add_contract(http, source.project_id, name, config)
    target, report, _ = replay(http, source, target_contract_version=name)
    assert report["verdict"] == "pass", report["replay"]["issues"]
    comparison = compare(http, source, target)
    assert dimension in comparison["confounders"]
    assert not comparison["direct_put_comparison"] and not comparison["repair_verified"]
    save("e6-" + name + ".json", comparison)


def test_e6_controlled_mode_names_actual_boundaries(live_stack, e6_source):
    source, _ = e6_source
    target, report, _ = replay(live_stack["http"], source, mode="controlled")
    assert report["verdict"] == "pass" and report["replay"]["mode"] == "controlled"
    manifest = report["replay"]["manifest"]
    assert manifest["external_clock_control"] is False and manifest["time_mode"] == "event_compressed"
    assert manifest["control_boundary"]["deterministic_external_staging"] is False
    assert "network_latency" in manifest["control_boundary"]["uncontrolled"]
    save("e6-controlled.json", {"report": report, "compare": compare(live_stack["http"], source, target)})


def test_e6_rejects_output_reuse_and_wrong_version_cross_project(live_stack, e6_source):
    scope, _ = e6_source
    http = live_stack["http"]
    request = {
        "project_id": str(scope.project_id),
        "mode": "input",
        "target_contract_version": "fixed",
        "target_product_version": "fixed",
        "idempotency_key": uuid4().hex,
    }
    for invalid in [
        request | {"reuse_product_outputs": True},
        request | {"target_product_version": "buggy"},
        request | {"mode": "history"},
    ]:
        assert http.post(BASE + f"/api/runs/{scope.run_id}/replay", json=invalid).status_code == 422
    assert (
        http.get(BASE + f"/api/runs/{scope.run_id}/history", params={"project_id": str(uuid4())}).status_code
        == 404
    )
    assert (
        http.put(
            BASE + f"/api/projects/{scope.project_id}/contract",
            json={"version": "buggy", "config": config_for("fixed")},
        ).status_code
        == 409
    )


def test_e6_all_twenty_input_scenarios_keep_e5_semantics(live_stack):
    source, report = setup_project(live_stack["http"], tuple(f"S{i:02}" for i in range(1, 21)), "fixed")
    save("e6-all-twenty-baseline.json", report)
    assert report["verdict"] == "pass" and report["gate"]["verdict"] == "pass", report["replay"]["issues"]
    target, replayed, _ = replay(live_stack["http"], source)
    save("e6-all-twenty-input.json", replayed)
    assert replayed["verdict"] == "pass" and replayed["gate"]["verdict"] == "pass", replayed["replay"][
        "issues"
    ]
    assert replayed["runtime"]["worker_recovery_verified"]
    assert all(f["verified"] for f in replayed["runtime"]["faults"])
    assert all(g["verified"] for g in replayed["runtime"]["concurrency"])


def test_e6_controlled_rejects_changed_control_conditions(live_stack, e6_source):
    source, _ = e6_source
    config = config_for("fixed", time_mode="realtime")
    add_contract(live_stack["http"], source.project_id, "different-time", config)
    result = live_stack["http"].post(
        BASE + f"/api/runs/{source.run_id}/replay",
        json={
            "project_id": str(source.project_id),
            "mode": "controlled",
            "target_contract_version": "different-time",
            "target_product_version": "fixed",
            "idempotency_key": uuid4().hex,
        },
    )
    assert result.status_code == 422 and "controlled" in result.text
