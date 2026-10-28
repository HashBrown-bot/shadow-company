"""E4 acceptance against separate HTTP processes and a real PostgreSQL database."""

import json
import os
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import text

from packages.contracts.config import Configuration
from packages.evaluators.refund import Policy, evaluate
from packages.simulator.e4 import SCENARIOS
from packages.transport.security import Scope, canonical, digest, headers

BASE = "http://127.0.0.1:8000"


def config_for(version="fixed"):
    value = yaml.safe_load(Path("environments/refund_approval/local.e4.yaml").read_text())
    value["product"]["version"] = version
    return value


def start(http, config=None, scenarios=SCENARIOS):
    config = config or config_for()
    p = http.post(BASE + "/api/projects", json={"name": "示例 E4 " + uuid4().hex}).json()["id"]
    response = http.put(BASE + f"/api/projects/{p}/contract", json={"version": "e4-v1", "config": config})
    assert response.status_code == 200, response.text
    response = http.post(BASE + f"/api/projects/{p}/preflight", json={"contract_version": "e4-v1"})
    assert response.status_code == 200 and response.json()["passed"], response.text
    response = http.post(
        BASE + "/api/runs",
        json={
            "project_id": p,
            "contract_version": "e4-v1",
            "idempotency_key": uuid4().hex,
            "suite_scope": "e4_core_10",
            "scenarios": list(scenarios),
        },
    )
    assert response.status_code == 202, response.text
    return Scope(project_id=p, run_id=response.json()["run_id"])


def wait_report(http, scope):
    deadline = time.monotonic() + 25
    while True:
        run = http.get(
            BASE + f"/api/runs/{scope.run_id}", params={"project_id": str(scope.project_id)}
        ).json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            response = http.get(
                BASE + f"/api/runs/{scope.run_id}/report", params={"project_id": str(scope.project_id)}
            )
            assert response.status_code == 200, response.text
            return response.json()
        assert time.monotonic() < deadline, run
        time.sleep(0.05)


@pytest.fixture(scope="module")
def fixed(live_stack):
    scope = start(live_stack["http"])
    result = wait_report(live_stack["http"], scope)
    return scope, result


def test_s01_s10_fixed_real_evidence_no_false_positives(fixed, live_stack):
    scope, report = fixed
    assert report["status"] == "completed", report.get("stop_reason")
    assert report["verdict"] == "pass", [
        (c["object_id"], c["rule_id"], c["verdict"], c["reason"])
        for c in report["checks"]
        if c["verdict"] not in {"pass", "not_applicable"}
    ]
    assert len(report["coverage"]) == 10 and all(c["verdict"] == "pass" for c in report["coverage"])
    assert {c["rule_id"] for c in report["checks"]} == {
        "REFUND_001",
        "REFUND_002",
        "APPROVAL_001",
        "STATE_001",
        "TIME_001",
    }
    assert report["gate"]["verdict"] == "inconclusive" and report["findings"] == []
    ledger = next(
        o["payload"]["response"]["body"] for o in report["observations"] if o["source"] == "provider_ledger"
    )
    entries = ledger["entries"]
    assert len(entries) == 11
    assert sum(e["amount_minor"] for e in entries if e["payment_id"] == "payment-S06") == 10000
    assert len([e for e in entries if e["refund_command_id"] == "refund-S05"]) == 1
    assert {e["currency"] for e in entries if e["payment_id"].startswith("payment-S08")} == {"CNY", "USD"}
    assert {
        e["amount_minor"]
        for e in entries
        if e["refund_command_id"] in {"refund-S01", "refund-S01-equal", "refund-S02"}
    } == {199999, 200000, 200001}
    access = report["access_checks"]
    assert len(access) == 2 and all(c["verdict"] == "pass" for c in access)
    forbidden = [
        o
        for o in report["observations"]
        if o["source"] == "put"
        and o["payload"].get("actor_id") == "customer_b"
        and o["payload"]["request"]["path"] == "/refunds/refund-S10"
    ]
    assert forbidden[0]["payload"]["response"]["status"] == 403
    low = [
        o
        for o in report["observations"]
        if o["source"] == "put" and o["payload"]["request"]["path"] == "/refunds/refund-S09/approve"
    ]
    assert low[0]["payload"]["actor_id"] == "support" and low[0]["payload"]["response"]["status"] == 403
    with live_stack["db"].connect() as c:
        assert c.execute(
            text("SELECT count(*) FROM check_results WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar() >= len(report["checks"])
        assert (
            c.execute(
                text("SELECT count(*) FROM evaluations WHERE project_id=:p AND run_id=:r"), scope.params
            ).scalar()
            >= 1
        )
    destination = Path(os.environ.get("ACCEPTANCE_EVIDENCE_DIR", "docs/evidence/e4"))
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "fixed-s01-s10.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


def test_buggy_duplicate_stale_approval_and_over_refund(live_stack):
    scope = start(live_stack["http"], config_for("buggy"), ["S04", "S05", "S07"])
    report = wait_report(live_stack["http"], scope)
    assert report["status"] == "completed" and report["verdict"] == "fail", report
    failed = {(c["rule_id"], c["object_id"]) for c in report["checks"] if c["verdict"] == "fail"}
    assert ("REFUND_001", "refund-S05") in failed
    assert ("APPROVAL_001", "refund-S04") in failed
    assert ("REFUND_002", "refund-S07-b") in failed
    assert ("STATE_001", "refund-S05") in failed
    assert all(
        f["severity"] == "critical"
        and f["confirmation"] == "confirmed"
        and f["attribution"] == "product_defect"
        for f in report["findings"]
        if f["rule_id"] in {"REFUND_001", "REFUND_002", "APPROVAL_001"} and f["confirmation"] == "confirmed"
    )
    repeat = (
        live_stack["http"]
        .get(BASE + f"/api/runs/{scope.run_id}/report", params={"project_id": str(scope.project_id)})
        .json()
    )
    assert repeat["evaluation_id"] == report["evaluation_id"]
    with live_stack["db"].connect() as c:
        assert c.execute(
            text("SELECT count(*) FROM findings WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar() == len(report["findings"])
    destination = Path(os.environ.get("ACCEPTANCE_EVIDENCE_DIR", "docs/evidence/e4"))
    (destination / "buggy.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


def test_missing_persisted_ledger_cannot_keep_cached_pass(fixed, live_stack):
    # Use another scope so the reusable fixed evidence remains intact.
    scope = start(live_stack["http"], scenarios=["S01"])
    result = wait_report(live_stack["http"], scope)
    assert result["verdict"] == "pass"
    audit = uuid4()
    with live_stack["db"].begin() as c:
        payload = {"purpose": "E4 audited negative evidence-loss test"}
        c.execute(
            text(
                "INSERT INTO reset_audits(project_id,run_id,reset_id,payload,content_hash) VALUES (:p,:r,:id,CAST(:v AS jsonb),:h)"
            ),
            scope.params | {"id": audit, "v": canonical(payload), "h": digest(payload)},
        )
        c.execute(text("SELECT set_config('simulation.reset_id',:id,true)"), {"id": str(audit)})
        c.execute(
            text("DELETE FROM observations WHERE project_id=:p AND run_id=:r AND source='provider_ledger'"),
            scope.params,
        )
    lost = (
        live_stack["http"]
        .get(BASE + f"/api/runs/{scope.run_id}/report", params={"project_id": str(scope.project_id)})
        .json()
    )
    assert lost["verdict"] == "inconclusive" and lost["evaluation_id"] != result["evaluation_id"]
    assert all(c["verdict"] == "inconclusive" for c in lost["checks"]), lost["checks"]
    assert (
        len(
            live_stack["http"]
            .get("http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope))
            .json()["entries"]
        )
        == 2
    )


def test_html_escaped_refs_and_scope(fixed, live_stack):
    scope, report = fixed
    from packages.evaluators.reporting import render_html

    response = live_stack["http"].get(
        BASE + f"/api/runs/{scope.run_id}/report",
        params={"project_id": str(scope.project_id), "format": "html"},
    )
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]
    assert "default-src 'none'" in response.headers["content-security-policy"]
    for value in ["REFUND_001", "未验证项", "预算", "失败链", "S10"]:
        assert value in response.text
    assert all('id="e-' + o["observation_id"] + '"' in response.text for o in report["observations"])
    malicious = deepcopy(report)
    malicious["limits"] = ["<script>alert('x')</script>"]
    assert "<script>" not in render_html(malicious) and "&lt;script&gt;" in render_html(malicious)
    destination = Path(os.environ.get("ACCEPTANCE_EVIDENCE_DIR", "docs/evidence/e4"))
    (destination / "fixed-report.html").write_text(response.text)


def test_evaluator_does_not_read_scenario_inputs_or_target_selectors(fixed):
    scope, report = fixed
    policy = Policy.from_config(Configuration.model_validate(config_for()))
    baseline = evaluate(policy, report["observations"], scope, completed=True)
    noise = deepcopy(report["observations"])
    for observation in noise:
        if observation["payload"].get("request", {}).get("path") == "/test/behavior":
            observation["payload"] = {"variant": "anything", "expected_verdict": "fail"}
    actual = evaluate(policy, noise, scope, completed=True)
    assert [(c["rule_id"], c["object_id"], c["verdict"]) for c in actual["checks"]] == [
        (c["rule_id"], c["object_id"], c["verdict"]) for c in baseline["checks"]
    ]


def test_real_put_false_success_has_no_provider_execution(live_stack):
    from threading import Event

    from adapters.http.refund import RefundAdapter
    from packages.evaluators.reporting import report as render_report
    from packages.simulator.e3 import new_run
    from tests.test_migrations import seed_run

    cfg = config_for()
    values = seed_run(live_stack["db"], cfg)
    scope = Scope(project_id=values["p"], run_id=uuid4())
    config = Configuration.model_validate(cfg)
    with live_stack["db"].begin() as c:
        binding = new_run(
            c,
            scope,
            "v1",
            config,
            {
                "kind": "e4_rules",
                "request": {"scenarios": ["S01"]},
                "plan": {"scenario_objects": {"S01": ["false-success"]}},
            },
        )
    adapter = RefundAdapter(live_stack["db"], scope, config)
    seed = {
        "payments": [{"payment_id": "payment", "amount_minor": 1000000, "currency": "CNY"}],
        "binding_id": str(binding),
    }
    for target, role in [("put", "put_admin"), ("provider", "provider_admin")]:
        assert adapter.call(target, role, "POST", "/test/seed", seed)["status"] == 200
    assert (
        adapter.call("put", "put_admin", "POST", "/test/behavior", {"variant": "false_success"})["status"]
        == 200
    )
    for role in ["support", "approver"]:
        assert adapter.call("put", role, "GET", "/identity")["status"] == 200
    assert (
        adapter.action(
            "request_refund",
            "false-success",
            {
                "refund_command_id": "false-success",
                "payment_id": "payment",
                "amount_minor": 10000,
                "currency": "CNY",
                "recipient": "demo-recipient",
            },
        )["status"]
        == 201
    )
    assert adapter.action("execute_refund", "false-success")["body"]["status"] == "succeeded"
    Event().wait(1.05)  # Contractual wall-clock observation, not a concurrency test.
    assert adapter.action("read_refund", "false-success")["body"]["status"] == "succeeded"
    assert adapter.ledger()["body"]["entries"] == []
    with live_stack["db"].begin() as c:
        c.execute(
            text(
                "UPDATE runs SET status='completed',stop_reason='e4_scope_complete' WHERE project_id=:p AND run_id=:r"
            ),
            scope.params,
        )
    result = render_report(live_stack["db"], scope)
    assert result["verdict"] == "fail"
    assert any(
        c["rule_id"] == "STATE_001" and c["verdict"] == "fail" and "没有执行" in c["reason"]
        for c in result["checks"]
    )
    destination = Path(os.environ.get("ACCEPTANCE_EVIDENCE_DIR", "docs/evidence/e4"))
    (destination / "false-success.json").write_text(
        json.dumps(result, default=str, ensure_ascii=False, indent=2)
    )


def test_conflicting_signed_callback_retained_and_reported(live_stack):
    from packages.transport.security import signature

    scope = start(live_stack["http"], scenarios=["S02"])
    initial = wait_report(live_stack["http"], scope)
    assert initial["verdict"] == "pass"
    with live_stack["db"].connect() as c:
        binding = c.execute(
            text("SELECT binding_id FROM webhook_bindings WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()
        event = c.execute(
            text("SELECT payload FROM payment_provider.outbox WHERE project_id=:p AND run_id=:r"),
            scope.params,
        ).scalar_one()
    event["amount_minor"] += 1
    encoded, stamp = canonical(event).encode(), int(time.time())
    response = live_stack["http"].post(
        BASE + "/api/webhooks/" + str(binding),
        content=encoded,
        headers={"X-Webhook-Timestamp": str(stamp), "X-Webhook-Signature": signature(scope, stamp, encoded)},
    )
    assert response.status_code == 409
    result = (
        live_stack["http"]
        .get(BASE + f"/api/runs/{scope.run_id}/report", params={"project_id": str(scope.project_id)})
        .json()
    )
    assert len([o for o in result["observations"] if o["source"] == "provider_webhook"]) == 2
    assert result["verdict"] == "inconclusive" and result["observation_conflicts"]


def test_e4_budget_reports_usage_and_no_pass(live_stack):
    config = config_for()
    config["runtime"]["max_events"] = 3
    scope = start(live_stack["http"], config, ["S01"])
    report = wait_report(live_stack["http"], scope)
    assert report["status"] == "failed" and report["stop_reason"] == "budget_exhausted"
    assert report["verdict"] == "inconclusive"
    assert report["budget"]["used"]["events_used"] == 3
    assert report["budget"]["used"]["attempted_events"] == 4


def test_e4_reset_removes_checks_findings_evaluations(live_stack):
    scope = start(live_stack["http"], config_for("buggy"), ["S05"])
    assert wait_report(live_stack["http"], scope)["verdict"] == "fail"
    result = live_stack["http"].post(
        BASE + f"/api/runs/{scope.run_id}/reset", params={"project_id": str(scope.project_id)}
    )
    assert result.status_code == 200, result.text
    with live_stack["db"].connect() as c:
        for table in ("check_results", "findings", "evaluations", "observations"):
            assert (
                c.execute(
                    text(f"SELECT count(*) FROM {table} WHERE project_id=:p AND run_id=:r"), scope.params
                ).scalar_one()
                == 0
            )


def test_new_evidence_keeps_finding_identity_and_historical_evaluation(live_stack):
    from packages.evidence.store import append

    scope = start(live_stack["http"], config_for("buggy"), ["S05"])
    before = wait_report(live_stack["http"], scope)
    with live_stack["db"].begin() as c:
        append(
            c,
            scope,
            "put",
            "health",
            "product_observation",
            {"request": {"path": "/health"}, "response": {"status": 200, "body": {"example": True}}},
        )
    after = (
        live_stack["http"]
        .get(BASE + f"/api/runs/{scope.run_id}/report", params={"project_id": str(scope.project_id)})
        .json()
    )
    assert after["evaluation_id"] != before["evaluation_id"]
    assert {f["finding_id"] for f in before["findings"]} == {f["finding_id"] for f in after["findings"]}
    with live_stack["db"].connect() as c:
        history = c.execute(
            text("SELECT payload FROM evaluations WHERE project_id=:p AND run_id=:r AND evaluation_id=:id"),
            scope.params | {"id": before["evaluation_id"]},
        ).scalar_one()
        assert history["checks"] == before["checks"]
        stored = c.execute(
            text("SELECT finding_id,check_id FROM findings WHERE project_id=:p AND run_id=:r"), scope.params
        ).all()
        assert {(str(f), str(check)) for f, check in stored} == {
            (f["finding_id"], f["check_id"]) for f in after["findings"]
        }


def test_e4_rejects_omitted_registered_rule(live_stack):
    from tests.test_e3_live import project_contract

    cfg = config_for()
    cfg["rules"] = [r for r in cfg["rules"] if r["id"] != "TIME_001"]
    p = project_contract(live_stack["http"], cfg)
    response = live_stack["http"].post(
        BASE + "/api/runs",
        json={
            "project_id": p,
            "contract_version": "e3-v1",
            "idempotency_key": uuid4().hex,
            "suite_scope": "e4_core_10",
            "scenarios": ["S01"],
        },
    )
    assert response.status_code == 422 and "五条" in response.text


def test_missing_intentional_repeat_is_unverified_coverage(live_stack):
    scope = start(live_stack["http"], scenarios=["S05"])
    before = wait_report(live_stack["http"], scope)
    assert before["verdict"] == "pass"
    executions = [
        o
        for o in before["observations"]
        if o["source"] == "put" and o["payload"]["request"]["path"] == "/refunds/refund-S05/execute"
    ]
    assert len(executions) == 2
    audit, payload = (
        uuid4(),
        {"purpose": "E4 negative coverage loss; business facts alone do not prove repeated input"},
    )
    with live_stack["db"].begin() as c:
        c.execute(
            text(
                "INSERT INTO reset_audits(project_id,run_id,reset_id,payload,content_hash) VALUES (:p,:r,:id,CAST(:v AS jsonb),:h)"
            ),
            scope.params | {"id": audit, "v": canonical(payload), "h": digest(payload)},
        )
        c.execute(text("SELECT set_config('simulation.reset_id',:id,true)"), {"id": str(audit)})
        c.execute(
            text("DELETE FROM observations WHERE project_id=:p AND run_id=:r AND observation_id=:id"),
            scope.params | {"id": executions[0]["observation_id"]},
        )
    run = (
        live_stack["http"]
        .get(BASE + f"/api/runs/{scope.run_id}", params={"project_id": str(scope.project_id)})
        .json()
    )
    assert run["verdict"] == "inconclusive"
    report = (
        live_stack["http"]
        .get(BASE + f"/api/runs/{scope.run_id}/report", params={"project_id": str(scope.project_id)})
        .json()
    )
    coverage = next(c for c in report["coverage"] if c["scenario_id"] == "S05")
    assert (
        coverage["status"] == "unverified"
        and coverage["actions_observed"] == 3
        and coverage["actions_required"] == 4
    )


def test_signed_illegal_business_callback_is_saved_even_when_protocol_rejected(live_stack):
    from packages.transport.security import signature

    scope = start(live_stack["http"], scenarios=["S02"])
    assert wait_report(live_stack["http"], scope)["verdict"] == "pass"
    with live_stack["db"].connect() as c:
        binding = c.execute(
            text("SELECT binding_id FROM webhook_bindings WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()
        event = c.execute(
            text("SELECT payload FROM payment_provider.outbox WHERE project_id=:p AND run_id=:r"),
            scope.params,
        ).scalar_one()
    for amount in [-1, 1.5]:
        encoded = canonical(event | {"amount_minor": amount}).encode()
        now = int(time.time())
        response = live_stack["http"].post(
            BASE + "/api/webhooks/" + str(binding),
            content=encoded,
            headers={"X-Webhook-Timestamp": str(now), "X-Webhook-Signature": signature(scope, now, encoded)},
        )
        assert response.status_code == 422
    run = (
        live_stack["http"]
        .get(BASE + f"/api/runs/{scope.run_id}", params={"project_id": str(scope.project_id)})
        .json()
    )
    assert run["verdict"] == "inconclusive"
    result = (
        live_stack["http"]
        .get(BASE + f"/api/runs/{scope.run_id}/report", params={"project_id": str(scope.project_id)})
        .json()
    )
    values = [
        o["payload"]["amount_minor"] for o in result["observations"] if o["source"] == "provider_webhook"
    ]
    assert -1 in values and 1.5 in values and len(values) == 3
    assert result["observation_conflicts"]


def test_e3_request_key_hash_stays_compatible_with_pre_e4_inputs(live_stack):
    from tests.test_e3_live import project_contract, run

    http = live_stack["http"]
    p = project_contract(http)
    assert http.post(BASE + f"/api/projects/{p}/preflight", json={"contract_version": "e3-v1"}).json()[
        "passed"
    ]
    rid, _, original_request = run(http, p, ["S01"])
    with live_stack["db"].connect() as c:
        stored_hash = c.execute(
            text("SELECT request_hash FROM run_inputs WHERE project_id=:p AND run_id=:r"), {"p": p, "r": rid}
        ).scalar_one()
    assert stored_hash == digest(original_request)
    retry = http.post(BASE + "/api/runs", json=original_request | {"suite_scope": "e3_smoke"})
    assert retry.status_code == 202 and retry.json()["run_id"] == rid
