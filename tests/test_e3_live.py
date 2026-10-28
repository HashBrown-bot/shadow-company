import json
import time
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import text

from packages.evaluators.e3 import evaluate
from packages.transport.security import Scope, canonical, headers, signature, token

BASE = "http://127.0.0.1:8000"


def project_contract(http, config=None):
    config = config or yaml.safe_load(Path("environments/refund_approval/local.e3.yaml").read_text())
    response = http.post(BASE + "/api/projects", json={"name": "示例 E3 集成验证 " + uuid4().hex})
    response.raise_for_status()
    p = response.json()["id"]
    response = http.put(BASE + f"/api/projects/{p}/contract", json={"version": "e3-v1", "config": config})
    assert response.status_code == 200, response.text
    return p


def run(http, p, scenarios=None, key=None):
    body = {
        "project_id": p,
        "contract_version": "e3-v1",
        "idempotency_key": key or uuid4().hex,
        "scenarios": scenarios or ["S01", "S02"],
    }
    response = http.post(BASE + "/api/runs", json=body)
    assert response.status_code == 202, response.text
    rid = response.json()["run_id"]
    deadline = time.monotonic() + 25
    while True:
        report = http.get(BASE + f"/api/runs/{rid}/report", params={"project_id": p}).json()
        if report["status"] in {"completed", "failed", "cancelled"}:
            break
        assert time.monotonic() < deadline, report
        time.sleep(0.05)
    return rid, report, body


@pytest.fixture
def activated(live_stack):
    http = live_stack["http"]
    p = project_contract(http)
    before = http.post(
        BASE + "/api/runs",
        json={
            "project_id": p,
            "contract_version": "e3-v1",
            "idempotency_key": "before",
            "scenarios": ["S01"],
        },
    )
    assert before.status_code == 409
    response = http.post(BASE + f"/api/projects/{p}/preflight", json={"contract_version": "e3-v1"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["passed"] is True, result
    assert result["business_verdict"] == "inconclusive"
    assert all(result["checks"].values())
    return http, p, result


def test_s01_s02_real_call_chain_and_independent_ledger(activated, live_stack):
    http, p, preflight = activated
    rid, report, body = run(http, p)
    assert report["status"] == "completed", report
    assert report["e3_flow"] == "pass", report
    assert report["verdict"] == "inconclusive" and report["gate"]["verdict"] == "inconclusive"
    assert [c["scenario_id"] for c in report["checks"]] == ["S01", "S02"]
    assert all(c["verdict"] == "pass" and c["provider_entry_ids"] for c in report["checks"])
    scope = Scope(project_id=p, run_id=rid)
    raw = http.get("http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope)).json()
    assert len(raw["entries"]) == 2
    assert {e["entry_id"] for e in raw["entries"]} == {c["provider_entry_ids"][0] for c in report["checks"]}
    assert all(c["put_delivered"] and c["platform_delivered"] for c in raw["callbacks"])
    with live_stack["db"].connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM refund_put.receipts WHERE project_id=:p AND run_id=:r"),
                scope.params,
            ).scalar_one()
            == 2
        )
        assert (
            c.execute(
                text("SELECT count(*) FROM webhook_receipts WHERE project_id=:p AND run_id=:r"), scope.params
            ).scalar_one()
            == 2
        )
        expected = c.execute(
            text("SELECT payload FROM run_inputs WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()["expected"]
    assert (
        evaluate(expected, [o for o in report["observations"] if o["source"] != "provider_ledger"], scope)[
            "verdict"
        ]
        == "inconclusive"
    )
    # Recipients are pseudonymized but monetary values and source references remain useful.
    serialized = json.dumps(report)
    assert token("support", scope) not in serialized and "Bearer " not in serialized
    duplicate = http.post(BASE + "/api/runs", json=body)
    assert duplicate.status_code == 202 and duplicate.json()["run_id"] == rid
    changed = body | {"scenarios": ["S01"]}
    assert http.post(BASE + "/api/runs", json=changed).status_code == 409
    assert http.get(BASE + f"/api/runs/{rid}", params={"project_id": str(uuid4())}).status_code == 404
    import os

    evidence = Path(os.environ.get("ACCEPTANCE_EVIDENCE_DIR", "docs/evidence/e3"))
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "call-chain.json").write_text(
        json.dumps({"preflight": preflight, "report": report}, ensure_ascii=False, indent=2) + "\n"
    )


def test_two_runs_same_external_ids_and_complete_reset(activated, live_stack):
    http, p, _ = activated
    r1, rep1, _ = run(http, p)
    r2, rep2, _ = run(http, p)
    assert rep1["e3_flow"] == rep2["e3_flow"] == "pass"
    s1, s2 = Scope(project_id=p, run_id=r1), Scope(project_id=p, run_id=r2)
    ids1 = {c["provider_entry_ids"][0] for c in rep1["checks"]}
    ids2 = {c["provider_entry_ids"][0] for c in rep2["checks"]}
    assert ids1.isdisjoint(ids2)
    # A token valid for r1 must not work after only swapping the scope headers.
    forged = headers("support", s1) | {"X-Run-ID": r2, "X-Run-Namespace": s2.namespace}
    assert http.get("http://127.0.0.1:8001/refunds/refund-S01", headers=forged).status_code == 403
    assert (
        http.get("http://127.0.0.1:8002/test/ledger", headers=headers("provider_execute", s1)).status_code
        == 403
    )
    assert http.get("http://127.0.0.1:8002/test/ledger", headers=headers("support", s1)).status_code == 403
    reset = http.post(BASE + f"/api/runs/{r1}/reset", params={"project_id": p})
    assert reset.status_code == 200, reset.text
    assert reset.json()["remote"]["provider"]["removed"]["ledger"] == 2
    with live_stack["db"].connect() as c:
        for table in [
            "observations",
            "events",
            "actions",
            "check_results",
            "jobs",
            "webhook_receipts",
            "webhook_bindings",
            "refund_put.namespaces",
            "refund_put.payments",
            "refund_put.refunds",
            "refund_put.receipts",
            "payment_provider.namespaces",
            "payment_provider.payments",
            "payment_provider.ledger",
            "payment_provider.outbox",
        ]:
            assert (
                c.execute(
                    text(f"SELECT count(*) FROM {table} WHERE project_id=:p AND run_id=:r"), s1.params
                ).scalar_one()
                == 0
            ), table
        assert (
            c.execute(
                text("SELECT count(*) FROM reset_audits WHERE project_id=:p AND run_id=:r"), s1.params
            ).scalar_one()
            == 1
        )
    assert (
        http.get("http://127.0.0.1:8001/refunds/refund-S01", headers=headers("support", s1)).status_code
        == 404
    )
    assert (
        http.get(BASE + f"/api/runs/{r1}/report", params={"project_id": p}).json()["e3_flow"]
        == "inconclusive"
    )
    assert http.get(BASE + f"/api/runs/{r2}/report", params={"project_id": p}).json()["e3_flow"] == "pass"
    assert http.post(BASE + f"/api/runs/{r1}/reset", params={"project_id": p}).status_code == 200


def test_real_partial_refund_idempotency_approval_and_role_requests(activated):
    http, p, _ = activated
    rid, report, _ = run(http, p, ["S01"])
    assert report["e3_flow"] == "pass"
    s = Scope(project_id=p, run_id=rid)
    support = headers("support", s)
    approver = headers("approver", s)
    command = {
        "refund_command_id": "partial-2",
        "payment_id": "payment-S01",
        "amount_minor": 250000,
        "currency": "CNY",
        "recipient": "demo-recipient",
    }
    create = http.post("http://127.0.0.1:8001/refunds", headers=support, json=command)
    assert create.status_code == 201
    path = "http://127.0.0.1:8001/refunds/partial-2"
    assert http.post(path + "/execute", headers=support).status_code == 409
    assert http.post(path + "/approve", headers=support).status_code == 403
    approval = http.post(path + "/approve", headers=approver).json()["approval"]
    assert (
        approval["version"] == 1
        and approval["amount_minor"] == 250000
        and approval["approved_by"] == "approver"
    )
    first = http.post(path + "/execute", headers=support)
    assert first.status_code == 200
    second = http.post(path + "/execute", headers=support)
    assert second.json()["provider_entry_id"] == first.json()["provider_entry_id"]
    assert (
        http.post(
            "http://127.0.0.1:8001/refunds", headers=support, json=command | {"amount_minor": 300000}
        ).status_code
        == 409
    )
    ledger = http.get("http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", s)).json()
    assert len(ledger["entries"]) == 2 and sum(e["amount_minor"] for e in ledger["entries"]) == 260000
    too_much = command | {"refund_command_id": "over-limit", "amount_minor": 800000}
    assert http.post("http://127.0.0.1:8001/refunds", headers=support, json=too_much).status_code == 201
    assert http.post("http://127.0.0.1:8001/refunds/over-limit/approve", headers=approver).status_code == 200
    assert http.post("http://127.0.0.1:8001/refunds/over-limit/execute", headers=support).status_code == 409


def test_webhook_auth_window_dedup_scope_and_durable_receipt(activated, live_stack):
    http, p, _ = activated
    rid, report, _ = run(http, p, ["S01"])
    assert report["e3_flow"] == "pass"
    scope = Scope(project_id=p, run_id=rid)
    with live_stack["db"].connect() as c:
        binding = c.execute(
            text("SELECT binding_id FROM webhook_bindings WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()
        event = c.execute(
            text("SELECT payload FROM payment_provider.outbox WHERE project_id=:p AND run_id=:r"),
            scope.params,
        ).scalar_one()
    path = BASE + "/api/webhooks/" + str(binding)
    body = canonical(event).encode()
    stamp = int(time.time())
    signed = {"X-Webhook-Timestamp": str(stamp), "X-Webhook-Signature": signature(scope, stamp, body)}
    assert http.post(path, content=body).status_code == 401
    assert (
        http.post(path, content=body, headers=signed | {"X-Webhook-Signature": "invalid"}).status_code == 401
    )
    stale = stamp - 301
    assert (
        http.post(
            path,
            content=body,
            headers={"X-Webhook-Timestamp": str(stale), "X-Webhook-Signature": signature(scope, stale, body)},
        ).status_code
        == 401
    )
    duplicate = http.post(path, content=body, headers=signed)
    assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
    for change, status in [({"amount_minor": 1}, 409), ({"run_id": str(uuid4())}, 403)]:
        altered = canonical(event | change).encode()
        assert (
            http.post(
                path,
                content=altered,
                headers=signed | {"X-Webhook-Signature": signature(scope, stamp, altered)},
            ).status_code
            == status
        )
    with live_stack["db"].connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM webhook_receipts WHERE project_id=:p AND run_id=:r"), scope.params
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize(
    "change",
    [
        "metadata",
        "admin_port",
        "external",
        "same_service",
        "path",
        "credentials",
        "semantic",
        "policy",
        "version",
    ],
)
def test_preflight_rejects_unapproved_configuration_before_use(live_stack, change):
    http = live_stack["http"]
    config = yaml.safe_load(Path("environments/refund_approval/local.e3.yaml").read_text())
    if change == "metadata":
        config["product"]["base_url"] = "http://169.254.169.254:8001"
    if change == "admin_port":
        config["product"]["base_url"] = "http://127.0.0.1:55432"
    if change == "external":
        config["product"]["base_url"] = "http://example.com:8001"
    if change == "same_service":
        config["provider"]["base_url"] = config["product"]["base_url"]
    if change == "path":
        config["provider"]["ledger_path"] = "/health"
    if change == "credentials":
        config["product"]["credentials"]["support"] = "secret://staging/support"
    if change == "semantic":
        config["product"]["actions"]["request_refund"]["path"] = "/executions"
    if change == "policy":
        config["environment"]["approval_threshold_minor"] = 100
        config["rules"][2]["params"]["threshold_minor"] = 100
    if change == "version":
        config["product"]["version"] = "unreviewed"
    p = project_contract(http, config)
    result = http.post(BASE + f"/api/projects/{p}/preflight", json={"contract_version": "e3-v1"})
    assert result.status_code == 422, result.text


def test_budget_does_not_become_success(live_stack):
    http = live_stack["http"]
    config = yaml.safe_load(Path("environments/refund_approval/local.e3.yaml").read_text())
    config["runtime"]["max_events"] = 1
    p = project_contract(http, config)
    result = http.post(BASE + f"/api/projects/{p}/preflight", json={"contract_version": "e3-v1"})
    assert result.json()["passed"]
    rid, report, _ = run(http, p, ["S01"])
    assert (
        report["status"] == "failed"
        and report["e3_flow"] == "inconclusive"
        and report["verdict"] == "inconclusive"
    )


def test_removing_persisted_provider_observation_cannot_keep_success(activated, live_stack):
    from packages.transport.security import digest

    http, p, _ = activated
    rid, report, _ = run(http, p, ["S01"])
    assert report["e3_flow"] == "pass"
    scope = Scope(project_id=p, run_id=rid)
    audit = uuid4()
    # Controlled test-only evidence loss through the audited deletion path, never bypassing DB triggers.
    with live_stack["db"].begin() as c:
        payload = {
            "purpose": "E3 missing-evidence negative test",
            "removed_hashes": [
                o["digest"] for o in report["observations"] if o["source"] == "provider_ledger"
            ],
        }
        c.execute(
            text(
                "INSERT INTO reset_audits (project_id,run_id,reset_id,payload,content_hash) VALUES (:p,:r,:id,CAST(:v AS jsonb),:h)"
            ),
            scope.params | {"id": audit, "v": canonical(payload), "h": digest(payload)},
        )
        c.execute(text("SELECT set_config('simulation.reset_id',:id,true)"), {"id": str(audit)})
        c.execute(
            text("DELETE FROM observations WHERE project_id=:p AND run_id=:r AND source='provider_ledger'"),
            scope.params,
        )
    result = http.get(BASE + f"/api/runs/{rid}/report", params={"project_id": p}).json()
    assert result["status"] == "completed" and result["e3_flow"] == "inconclusive"
    assert all(c["verdict"] == "inconclusive" for c in result["checks"])
    # The independent ledger still exists: proof of its availability isn't substituted for captured evidence.
    assert (
        len(
            http.get("http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope)).json()[
                "entries"
            ]
        )
        == 1
    )


def test_frozen_inputs_cannot_be_changed_after_execution(activated, live_stack):
    from sqlalchemy.exc import IntegrityError

    http, p, _ = activated
    rid, _, body = run(http, p, ["S01"])
    scope = Scope(project_id=p, run_id=rid)
    with pytest.raises(IntegrityError, match="immutable run input"):
        with live_stack["db"].begin() as c:
            c.execute(
                text("UPDATE run_inputs SET payload='{}' WHERE project_id=:p AND run_id=:r"), scope.params
            )
    assert http.post(BASE + f"/api/runs/{rid}/reset", params={"project_id": p}).status_code == 200
    # A reset does not make the old request key silently create a fresh payment run.
    again = http.post(BASE + "/api/runs", json=body)
    assert again.status_code == 202 and again.json()["run_id"] == rid


def test_two_projects_do_not_share_business_ids(activated, live_stack):
    http, p, _ = activated
    first, _, _ = run(http, p, ["S01"])
    p2 = project_contract(http)
    assert http.post(BASE + f"/api/projects/{p2}/preflight", json={"contract_version": "e3-v1"}).json()[
        "passed"
    ]
    second, report, _ = run(http, p2, ["S01"])
    assert report["e3_flow"] == "pass"
    wrong = Scope(project_id=p2, run_id=first)
    assert (
        http.get("http://127.0.0.1:8001/refunds/refund-S01", headers=headers("support", wrong)).status_code
        == 404
    )
    assert http.get(BASE + f"/api/runs/{second}/report", params={"project_id": p}).status_code == 404


def test_e3_never_persists_unregistered_rule_results(activated, live_stack):
    http, p, _ = activated
    rid, report, _ = run(http, p, ["S01"])
    assert report["e3_flow"] == "pass"
    scope = Scope(project_id=p, run_id=rid)
    with live_stack["db"].connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM check_results WHERE project_id=:p AND run_id=:r"), scope.params
            ).scalar_one()
            == 0
        )
    assert report["gate"]["verdict"] == "inconclusive"


def test_e3_evidence_correlation_rejects_conflicts_and_malformed_raw_values(activated, live_stack):
    from copy import deepcopy

    from packages.transport.security import digest

    http, p, _ = activated
    rid, report, _ = run(http, p, ["S01"])
    assert report["e3_flow"] == "pass"
    scope = Scope(project_id=p, run_id=rid)
    with live_stack["db"].connect() as c:
        expected = c.execute(
            text("SELECT payload FROM run_inputs WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()["expected"]
    # Negative evidence projections copied from a real execution, never expected-answer flags in the product.
    for source, field, value in [
        ("provider_ledger", "recipient", "sha256:" + digest("different-recipient")),
        ("put", "recipient", "sha256:" + digest("different-recipient")),
        ("put", "project_id", str(uuid4())),
        ("put", "refund_id", "another-command"),
        ("provider_ledger", "amount_minor", 10000.0),
        ("put", "amount_minor", 10000.0),
        ("provider_webhook", "run_id", str(uuid4())),
    ]:
        observations = deepcopy(report["observations"])
        for obs in observations:
            if obs["source"] != source:
                continue
            if source == "provider_ledger":
                obs["payload"]["response"]["body"]["entries"][0][field] = value
            elif (
                source == "put"
                and obs["payload"]["request"]["method"] == "GET"
                and obs["payload"]["request"]["path"] == "/refunds/refund-S01"
            ):
                obs["payload"]["response"]["body"][field] = value
            elif source == "provider_webhook":
                obs["payload"][field] = value
        assert evaluate(expected, observations, scope)["verdict"] == "fail", field
    for invalid in [None, "invalid", {}, [None]]:
        observations = deepcopy(report["observations"])
        for obs in observations:
            if obs["source"] == "provider_ledger":
                obs["payload"]["response"]["body"]["entries"] = invalid
        assert evaluate(expected, observations, scope)["verdict"] == "inconclusive"
