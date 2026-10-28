"""Protocol-level rule tests. Inputs are raw records, not simulator expected-answer flags."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from random import Random
from uuid import uuid4

import pytest

from packages.evaluators.refund import PERMISSIONS, Policy, evaluate
from packages.transport.security import Scope, digest

T0 = datetime(2026, 10, 7, tzinfo=timezone.utc)
POLICY = Policy(200000, 2)


def observation(scope, source, payload, second):
    return scope.model_dump(mode="json") | {
        "observation_id": str(uuid4()),
        "source": source,
        "evidence_kind": "product_observation" if source == "put" else "dependency_evidence",
        "captured_at": (T0 + timedelta(seconds=second)).isoformat(),
        "digest": digest(payload),
        "payload": deepcopy(payload),
    }


def call(scope, method, path, body, second, actor="support", request=None, status=200):
    return observation(
        scope,
        "put",
        {
            "actor_id": actor,
            "request": {"method": method, "path": path, "body": request},
            "response": {"status": status, "body": body},
        },
        second,
    )


def trace(amount=10000, approved=None, currency="CNY", command="r1", payment="p1", scope=None):
    scope = scope or Scope(project_id=uuid4(), run_id=uuid4())
    records = [
        call(
            scope,
            "GET",
            "/identity",
            scope.model_dump(mode="json") | {"identity_id": role, "permissions": list(permissions)},
            0,
            actor=role,
        )
        for role, permissions in PERMISSIONS.items()
    ]
    fields = {
        "refund_id": command,
        "payment_id": payment,
        "amount_minor": amount,
        "currency": currency,
        "recipient": "sha256:recipient",
        "version": 1,
        "owner_id": "customer_a",
    }
    request = {k: fields[k] for k in ("payment_id", "amount_minor", "currency", "recipient")} | {
        "refund_command_id": command
    }
    body = scope.model_dump(mode="json") | fields | {"status": "requested", "approval": None}
    records.append(call(scope, "POST", "/refunds", body, 1, request=request, status=201))
    approval = None
    if approved is True or approved is None and amount > POLICY.threshold_minor:
        approval = {
            k: fields[k] for k in ("refund_id", "amount_minor", "currency", "recipient", "version")
        } | {
            "approved_by": "approver",
            "approved": True,
            "approved_at": (T0 + timedelta(seconds=2)).isoformat(),
            "approval_id": str(uuid4()),
        }
        body = body | {"status": "approved", "approval": approval}
        records.append(call(scope, "POST", f"/refunds/{command}/approve", body, 2, actor="approver"))
    entry = scope.model_dump(mode="json") | {
        "entry_id": str(uuid4()),
        "refund_command_id": command,
        "payment_id": payment,
        "amount_minor": amount,
        "currency": currency,
        "recipient": fields["recipient"],
        "status": "succeeded",
        "created_at": (T0 + timedelta(seconds=3)).isoformat(),
        "command_version": 1,
        "approval": approval,
    }
    body = body | {"status": "succeeded", "provider_entry_id": entry["entry_id"]}
    records.append(call(scope, "POST", f"/refunds/{command}/execute", body, 3))
    records.append(observation(scope, "provider_webhook", entry | {"event_id": str(uuid4())}, 4))
    records.append(call(scope, "GET", f"/refunds/{command}", body, 8))
    records.append(
        observation(
            scope,
            "provider_ledger",
            {
                "response": {
                    "status": 200,
                    "body": scope.model_dump(mode="json")
                    | {
                        "complete": True,
                        "entries": [entry],
                        "payments": [
                            scope.model_dump(mode="json")
                            | {"payment_id": payment, "amount_minor": 1000000, "currency": currency}
                        ],
                    },
                }
            },
            8,
        )
    )
    return scope, records


def body(records, source="provider_ledger"):
    return next(o["payload"]["response"]["body"] for o in records if o["source"] == source)


def derive(scope, records, completed=True, at=9):
    for record in records:
        record["digest"] = digest(record["payload"])
    return evaluate(POLICY, records, scope, completed=completed, evaluated_at=T0 + timedelta(seconds=at))


def rule(result, name, command="r1"):
    return next(c for c in result["checks"] if c["rule_id"] == name and c["object_id"] == command)


@pytest.mark.parametrize(
    "amount,approved,verdict",
    [
        (199999, False, "not_applicable"),
        (200000, False, "not_applicable"),
        (200001, True, "pass"),
        (200001, False, "fail"),
    ],
)
def test_threshold_below_equal_above(amount, approved, verdict):
    scope, records = trace(amount, approved)
    result = derive(scope, records)
    assert rule(result, "APPROVAL_001")["verdict"] == verdict
    if verdict == "not_applicable":
        assert "契约" in rule(result, "APPROVAL_001")["reason"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 2),
        ("amount_minor", 200002),
        ("currency", "USD"),
        ("recipient", "other"),
        ("refund_id", "other"),
        ("approved_by", "support"),
        ("approved", False),
    ],
)
def test_each_approval_binding_and_authority(field, value):
    scope, records = trace(200001)
    body(records)["entries"][0]["approval"][field] = value
    assert rule(derive(scope, records), "APPROVAL_001")["verdict"] == "fail"


def test_claimed_approval_needs_actual_authorized_approval_observation():
    scope, records = trace(200001)
    records = [o for o in records if not o["payload"].get("request", {}).get("path", "").endswith("/approve")]
    assert rule(derive(scope, records), "APPROVAL_001")["verdict"] == "inconclusive"


def test_duplicate_entries_vs_repeated_snapshot_and_failed_attempts():
    scope, records = trace()
    ledger = body(records)
    ledger["entries"].append(
        ledger["entries"][0] | {"entry_id": str(uuid4()), "status": "failed", "amount_minor": 999999999}
    )
    records.append(deepcopy(records[-1]) | {"observation_id": str(uuid4())})
    result = derive(scope, records)
    assert rule(result, "REFUND_001")["verdict"] == "pass"
    assert rule(result, "REFUND_002")["actual"]["success_totals_by_currency"] == {"CNY": 10000}
    ledger["entries"].append(ledger["entries"][0] | {"entry_id": str(uuid4())})
    result = derive(scope, records)
    assert rule(result, "REFUND_001")["verdict"] == "fail"
    assert rule(result, "STATE_001")["verdict"] == "fail"


@pytest.mark.parametrize(
    "amount,currency", [(1000001, "CNY"), (10000, "USD"), (-1, "CNY"), (1.0, "CNY"), (True, "CNY")]
)
def test_over_balance_mismatch_and_illegal_business_values(amount, currency):
    scope, records = trace()
    body(records)["entries"][0].update(amount_minor=amount, currency=currency)
    assert rule(derive(scope, records), "REFUND_002")["verdict"] == "fail"


def test_partial_refunds_property_and_currency_separation():
    rng = Random(731)
    for _ in range(25):
        a, b = rng.randint(1, 90000), rng.randint(1, 90000)
        scope, first = trace(a, command="a", payment="p-cny")
        _, second = trace(b, command="b", payment="p-cny", scope=scope)
        _, usd = trace(a, command="c", payment="p-usd", currency="USD", scope=scope)
        ledger = body(first)
        ledger["entries"] += body(second)["entries"] + body(usd)["entries"]
        ledger["payments"] += body(usd)["payments"]
        records = first + [o for o in second + usd if o["source"] != "provider_ledger"]
        result = derive(scope, records)
        assert result["verdict"] == "pass", result["checks"]
        assert rule(result, "REFUND_002", "a")["actual"]["success_totals_by_currency"] == {"CNY": a + b}
        assert rule(result, "REFUND_002", "c")["actual"]["success_totals_by_currency"] == {"USD": a}


@pytest.mark.parametrize("source", ["provider_ledger", "provider_webhook", "final_query", "identity"])
def test_missing_required_evidence(source):
    scope, records = trace(200001)
    if source == "final_query":
        records = [
            o
            for o in records
            if not (
                o["source"] == "put"
                and o["payload"]["request"]["method"] == "GET"
                and o["payload"]["request"]["path"] == "/refunds/r1"
            )
        ]
    elif source == "identity":
        records = [o for o in records if o["payload"].get("request", {}).get("path") != "/identity"]
    else:
        records = [o for o in records if o["source"] != source]
    result = derive(scope, records)
    assert result["verdict"] == "inconclusive"
    assert rule(result, "APPROVAL_001")["verdict"] == "inconclusive"


def test_product_success_without_independent_execution_is_failure():
    scope, records = trace()
    body(records)["entries"] = []
    records = [o for o in records if o["source"] != "provider_webhook"]
    result = derive(scope, records)
    assert rule(result, "STATE_001")["verdict"] == "fail"


def test_terminal_regression_uses_observed_history():
    scope, records = trace()
    for o in records:
        if o["source"] == "put" and o["payload"]["request"]["path"] == "/refunds/r1":
            o["payload"]["response"]["body"]["status"] = "execution_pending"
    result = derive(scope, records)
    assert rule(result, "STATE_001")["verdict"] == "fail"


def pending_trace(at, final_status="execution_pending"):
    scope, records = trace()
    body(records)["entries"] = []
    records = [o for o in records if o["source"] != "provider_webhook"]
    for o in records:
        if o["source"] == "put" and o["payload"]["request"]["path"].endswith("/execute"):
            o["payload"]["response"]["body"]["status"] = "execution_pending"
        if o["source"] == "put" and o["payload"]["request"]["path"] == "/refunds/r1":
            o["captured_at"] = (T0 + timedelta(seconds=at)).isoformat()
            o["payload"]["response"]["body"]["status"] = final_status
        if o["source"] == "provider_ledger":
            o["captured_at"] = (T0 + timedelta(seconds=at)).isoformat()
    return scope, records


@pytest.mark.parametrize("at,verdict", [(4.999, "inconclusive"), (5, "fail"), (6, "fail")])
def test_time_window_before_at_after_deadline(at, verdict):
    scope, records = pending_trace(at)
    assert rule(derive(scope, records, at=at), "TIME_001")["verdict"] == verdict


def test_time_reconciliation_within_window_and_late_evidence():
    scope, records = pending_trace(5, "reconciliation_required")
    assert rule(derive(scope, records, at=5), "TIME_001")["verdict"] == "pass"
    records = [o for o in records if o["source"] != "provider_ledger"]
    assert rule(derive(scope, records, at=8), "TIME_001")["verdict"] == "inconclusive"


@pytest.mark.parametrize(
    "status,attribution", [(None, "adapter_error"), (503, "environment_error"), (422, "actor_error")]
)
def test_infrastructure_and_actor_errors_are_not_product_defects(status, attribution):
    scope, records = trace()
    for o in records:
        if o["payload"].get("request", {}).get("path", "").endswith("/execute"):
            o["payload"]["response"] = {"status": status, "body": {"error": "unavailable"}}
    result = derive(scope, records)
    assert result["verdict"] == "inconclusive"
    assert result["findings"] and all(
        f["attribution"] == attribution and f["confirmation"] == "unconfirmed" for f in result["findings"]
    )


def test_cancel_budget_unfinished_never_pass_and_refs_resolve():
    scope, records = trace()
    result = derive(scope, records, completed=False)
    assert result["verdict"] == "inconclusive"
    assert all(c["verdict"] == "inconclusive" for c in result["checks"])
    ids = {o["observation_id"] for o in records}
    assert all(set(c["evidence_refs"]) <= ids for c in result["checks"])


def test_same_entry_conflict_is_not_last_write_wins():
    scope, records = trace()
    later = deepcopy(records[-1]) | {"observation_id": str(uuid4())}
    later["payload"]["response"]["body"]["entries"][0]["amount_minor"] = 123
    records.append(later)
    result = derive(scope, records)
    assert result["verdict"] != "pass" and result["observation_conflicts"]
    assert records[-2]["observation_id"] in result["observation_conflicts"][0]["evidence_refs"]
    assert records[-1]["observation_id"] in result["observation_conflicts"][0]["evidence_refs"]


@pytest.mark.parametrize("value", [None, "bad", {}, [None]])
def test_malformed_ledger_is_inconclusive_not_crash(value):
    scope, records = trace()
    body(records)["entries"] = value
    result = derive(scope, records)
    assert result["verdict"] == "inconclusive"


def test_accepting_execution_without_a_terminal_cannot_pass():
    scope, records = pending_trace(6, "requested")
    for o in records:
        if o["payload"].get("request", {}).get("path", "").endswith("/execute"):
            o["payload"]["response"]["body"]["status"] = "requested"
    assert rule(derive(scope, records, at=6), "TIME_001")["verdict"] == "fail"


def test_ledger_omission_retains_conflict_and_never_passes():
    scope, records = trace()
    later = deepcopy(records[-1]) | {
        "observation_id": str(uuid4()),
        "captured_at": (T0 + timedelta(seconds=9)).isoformat(),
    }
    later["payload"]["response"]["body"]["entries"] = []
    records.append(later)
    result = derive(scope, records)
    assert result["verdict"] == "inconclusive"
    assert any("遗漏" in c["reason"] for c in result["observation_conflicts"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", ["succeeded"]),
        ("owner_id", {}),
        ("approval", "wrong"),
        ("recipient", {}),
        ("amount_minor", {}),
        ("version", True),
    ],
)
def test_malformed_product_values_do_not_crash_or_pass(field, value):
    scope, records = trace(200001)
    for o in records:
        if o["payload"].get("request", {}).get("path") == "/refunds/r1":
            o["payload"]["response"]["body"][field] = value
    result = derive(scope, records)
    # Ownership is needed only for customer access checks; all monetary/state facts
    # may still be established without it, so test the customer-query path as well.
    if field == "owner_id":
        q = next(o for o in records if o["payload"].get("request", {}).get("path") == "/refunds/r1")
        q = deepcopy(q) | {"observation_id": str(uuid4())}
        q["payload"]["actor_id"] = "customer_b"
        records.append(q)
        result = derive(scope, records)
    assert result["verdict"] != "pass"


def test_late_terminal_without_transition_timestamp_is_unknown_not_false_failure():
    scope, records = pending_trace(6, "reconciliation_required")
    assert rule(derive(scope, records, at=6), "TIME_001")["verdict"] == "inconclusive"


def test_dependency_failure_is_distinct_from_product_attribution():
    scope, records = pending_trace(5, "reconciliation_required")
    entry = {
        "entry_id": str(uuid4()),
        "refund_command_id": "r1",
        "payment_id": "p1",
        "amount_minor": 10000,
        "currency": "CNY",
        "status": "failed",
    } | scope.model_dump(mode="json")
    body(records)["entries"] = [entry]
    result = derive(scope, records)
    assert result["verdict"] == "inconclusive"
    assert all(f["attribution"] == "dependency_failure" for f in result["findings"])


def test_cross_customer_disclosure_yields_confirmed_finding():
    scope, records = trace()
    query = next(o for o in records if o["payload"].get("request", {}).get("path") == "/refunds/r1")
    leaked = deepcopy(query) | {"observation_id": str(uuid4())}
    leaked["payload"]["actor_id"] = "customer_b"
    records.append(leaked)
    result = derive(scope, records)
    assert result["access_checks"][0]["verdict"] == "fail"
    finding = next(f for f in result["findings"] if f["rule_id"] == "STATE_001")
    assert finding["confirmation"] == "confirmed" and finding["attribution"] == "product_defect"


def test_malformed_callback_identifier_is_inconclusive_not_a_crash():
    scope, records = trace()
    next(o for o in records if o["source"] == "provider_webhook")["payload"]["entry_id"] = {}
    assert derive(scope, records)["verdict"] == "inconclusive"
