"""REAL LOCAL HTTP/Worker/PostgreSQL. Models are disabled, not a model-service test."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from packages.contracts.actors import ActorPolicy
from packages.transport.security import Scope, canonical, digest
from tests.test_e4_live import BASE
from tests.test_e5_live import ALL, config_for, save, wait_report
from tests.test_e6_live import add_contract, get, replay

pytestmark = pytest.mark.live_local


def project(http, version="fixed", **runtime):
    p = http.post(BASE + "/api/projects", json={"name": "E7 本机规则/混合边界 " + uuid4().hex}).json()["id"]
    add_contract(http, p, version, config_for(version, **runtime))
    return p


def start(http, p, scenarios=ALL, version="fixed", policy=None):
    response = http.post(
        BASE + "/api/runs",
        json={
            "project_id": p,
            "contract_version": version,
            "idempotency_key": uuid4().hex,
            "suite_scope": "e7_core_20",
            "scenarios": list(scenarios),
            "actor_policy": (policy or ActorPolicy()).model_dump(mode="json"),
        },
    )
    assert response.status_code == 202, response.text
    scope = Scope(project_id=p, run_id=response.json()["run_id"])
    return scope, wait_report(http, scope)


def make_experiment(http, p, seeds=(17, 23), scenarios=("S01", "S09", "S10", "S12"), version="fixed"):
    body = {
        "project_id": p,
        "contract_version": version,
        "idempotency_key": uuid4().hex,
        "seeds": list(seeds),
        "scenarios": list(scenarios),
        "model_budget": {"max_calls": 4, "max_tokens": 10000},
    }
    response = http.post(BASE + "/api/experiments", json=body)
    assert response.status_code == 202, response.text
    experiment = response.json()
    for run in experiment["runs"]:
        report = wait_report(http, Scope(project_id=p, run_id=run["run_id"]))
        save("e7-pair-" + version + "-" + str(run["seed"]) + "-" + run["mode"] + ".json", report)
    return body, experiment


def experiment_result(http, p, e):
    response = http.get(BASE + "/api/experiments/" + e, params={"project_id": p})
    assert response.status_code == 200, response.text
    return response.json()


def test_e7_model_off_completes_all_twenty_and_real_permission_probes(live_stack):
    http = live_stack["http"]
    scope, result = start(http, project(http))
    save("e7-disabled-s01-s20.json", result)
    assert result["status"] == "completed" and result["gate"]["verdict"] == "pass", result["stop_reason"]
    assert result["scope"]["phase"] == "E7" and result["findings"] == []
    assert result["actors"]["calls"] == [] and result["budget"]["cost"]["model_calls"] == 0
    assert result["budget"]["cost"]["model_tokens"] == 0
    assert result["actors"]["model_service_test"] == "not_run"
    # Rule probes still reach the PUT; the model boundary is not substituted for PUT access tests.
    reads = [o["payload"] for o in result["observations"] if o["source"] == "put"]
    assert any(
        o.get("actor_id") == "support"
        and o.get("request", {}).get("path", "").endswith("/approve")
        and o.get("response", {}).get("status") == 403
        for o in reads
    )
    assert any(
        o.get("actor_id") == "customer_b" and o.get("response", {}).get("status") == 403 for o in reads
    )
    assert result["runtime"]["worker_recovery_verified"]
    assert any(j["kind"] == "e7_actor_route" for j in result["runtime"]["journal"])
    assert (
        get(http, scope, "manifest")["planned"]["payload"]["actor_policy"]["content_hash"]
        == result["actors"]["policy_hash"]
    )


def test_hybrid_api_routes_rule_even_when_protocol_adapter_enabled(live_stack):
    from tests.test_e7_actors import enabled

    http = live_stack["http"]
    scope, result = start(http, project(http), ["S01"], policy=enabled(max_calls=0, max_tokens=0))
    assert result["verdict"] == "pass" and result["actors"]["effective_strategy"] == "rule"
    assert result["actors"]["policy"]["model_enabled"]
    assert result["budget"]["cost"]["model_calls"] == 0
    assert result["actors"]["routing_reason"] == "ordinary_api_has_no_natural_language_entry"
    assert not result["actors"]["ai_increment_proven"]
    save("e7-hybrid-api-rule-fallback.json", result)
    _, target, _ = replay(http, scope)
    assert target["verdict"] == "pass" and target["actors"]["policy"] == result["actors"]["policy"]


def test_paired_seeds_same_conditions_unmeasured_metrics_and_idempotency(live_stack):
    http = live_stack["http"]
    p = project(http)
    body, experiment = make_experiment(http, p)
    result = experiment_result(http, p, experiment["experiment_id"])
    save("e7-experiment-fixed.json", result)
    assert result["paired_conditions_verified"], result["comparison_issues"]
    assert len(result["runs"]) == 4 and all(r["verdict"] == "pass" for r in result["runs"])
    for metric in result["metrics"].values():
        assert metric["observed_product_findings"] == 0
        assert metric["confirmed_independent_defects"] is None and metric["false_positives"] is None
        assert metric["human_confirmation_seconds"] is None and metric["review_measurement"] == "未测"
        assert metric["model_calls"] == metric["model_tokens"] == metric["estimated_model_cost_microusd"] == 0
        assert metric["cost_source"] == "no_model_calls_no_model_fee"
    again = http.post(BASE + "/api/experiments", json=body)
    assert again.status_code == 202 and again.json()["runs"] == experiment["runs"]
    changed = http.post(BASE + "/api/experiments", json=body | {"seeds": [99]})
    assert changed.status_code == 409
    assert (
        http.get(
            BASE + "/api/experiments/" + experiment["experiment_id"], params={"project_id": str(uuid4())}
        ).status_code
        == 404
    )
    page = http.get(
        BASE + "/api/experiments/" + experiment["experiment_id"], params={"project_id": p, "format": "html"}
    )
    assert page.status_code == 200 and "未证明 AI 增量" in page.text and "未测" in page.text


def test_independent_defects_require_explicit_reviews_not_finding_counts(live_stack):
    http = live_stack["http"]
    p = project(http, "buggy")
    _, experiment = make_experiment(http, p, seeds=[37], scenarios=["S12"], version="buggy")
    e = experiment["experiment_id"]
    before = experiment_result(http, p, e)
    assert before["paired_conditions_verified"] and all(r["verdict"] == "fail" for r in before["runs"])
    assert before["metrics"]["rule"]["observed_product_findings"] > 0
    assert before["metrics"]["rule"]["confirmed_independent_defects"] is None
    save("e7-experiment-buggy-unreviewed.json", before)
    # Synthetic review INPUTS test plumbing only. Never counted as a collected human experiment.
    for run in experiment["runs"]:
        result = get(http, Scope(project_id=p, run_id=run["run_id"]), "report")
        findings = [f for f in result["findings"] if f["attribution"] == "product_defect"]
        for f in findings:
            review = {
                "project_id": p,
                "run_id": run["run_id"],
                "finding_id": f["finding_id"],
                "decision": "confirmed",
                "root_cause_id": "synthetic-test-group",
                "reviewer": "protocol-test-only",
                "human_seconds": 13,
            }
            response = http.post(BASE + f"/api/experiments/{e}/reviews", json=review)
            assert response.status_code == 201, response.text
            assert http.post(BASE + f"/api/experiments/{e}/reviews", json=review).status_code == 201
            assert (
                http.post(
                    BASE + f"/api/experiments/{e}/reviews", json=review | {"human_seconds": 14}
                ).status_code
                == 409
            )
    after = experiment_result(http, p, e)
    for mode in ("rule", "hybrid"):
        assert after["metrics"][mode]["confirmed_independent_defects"] == 1
        assert (
            after["metrics"][mode]["human_confirmation_seconds"]
            == 13 * after["metrics"][mode]["reviewed_findings"]
        )
    assert not after["ai_increment_proven"]
    save(
        "e7-review-protocol-only.json",
        {"test_kind": "synthetic_review_input_protocol_test_not_collected_human_metrics", "result": after},
    )


def test_pair_budget_stop_cannot_report_pass_or_comparable(live_stack):
    http = live_stack["http"]
    p = project(http, max_events=1)
    _, experiment = make_experiment(http, p, seeds=[11], scenarios=["S01"])
    result = experiment_result(http, p, experiment["experiment_id"])
    assert not result["paired_conditions_verified"]
    assert all(r["status"] == "failed" and r["verdict"] != "pass" for r in result["runs"])
    save("e7-experiment-budget-stop.json", result)


def test_missing_policy_invalidates_pass_and_reset_is_scoped(live_stack):
    http, db = live_stack["http"], live_stack["db"]
    p = project(http)
    source, original = start(http, p, ["S01"])
    target, result = start(http, p, ["S01"], policy=ActorPolicy(mode="hybrid"))
    assert result["verdict"] == original["verdict"] == "pass"
    before = get(http, source, "history")
    with db.begin() as c:
        payload = {"test": "e7_policy_loss"}
        reset_id = uuid4()
        c.execute(
            text(
                "INSERT INTO reset_audits(project_id,run_id,reset_id,payload,content_hash) VALUES (:p,:r,:id,CAST(:v AS jsonb),:h)"
            ),
            target.params | {"id": reset_id, "v": canonical(payload), "h": digest(payload)},
        )
        c.execute(text("SELECT set_config('simulation.reset_id',:id,true)"), {"id": str(reset_id)})
        c.execute(text("DELETE FROM actor_policies WHERE project_id=:p AND run_id=:r"), target.params)
    changed = get(http, target, "report")
    assert (
        changed["verdict"] == "inconclusive"
        and "actor_policy_missing_or_corrupt" in changed["actors"]["issues"]
    )
    save("e7-policy-loss.json", changed)
    response = http.post(BASE + f"/api/runs/{source.run_id}/reset", params={"project_id": p})
    assert response.status_code == 200 and response.json()["removed"]["actor_policies"] == 1
    assert before["actor_policies"]
    assert get(http, target, "report")["verdict"] == "inconclusive"
