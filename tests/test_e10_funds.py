"""E10 independent counterexamples for incomplete funds evidence and approval types."""

from copy import deepcopy

import pytest

from tests.test_e4_rules import body, derive, rule, trace


@pytest.mark.parametrize("currency", [None, {}, [], True, 1, "", "UNKNOWN"])
def test_invalid_independent_payment_currency_is_inconclusive(currency):
    scope, records = trace(200001)
    body(records)["payments"][0]["currency"] = currency
    original = deepcopy(records)
    result = derive(scope, records)
    assert result["verdict"] == "inconclusive"
    assert rule(result, "REFUND_002")["verdict"] == "inconclusive"
    assert all(f["attribution"] != "product_defect" for f in result["findings"])
    assert [r["payload"] for r in records] == [r["payload"] for r in original]


def test_missing_independent_payment_currency_is_inconclusive():
    scope, records = trace(200001)
    del body(records)["payments"][0]["currency"]
    assert derive(scope, records)["verdict"] == "inconclusive"


@pytest.mark.parametrize("field,value", [("version", 1.0), ("version", True), ("amount_minor", 200001.0)])
@pytest.mark.parametrize("source", ["all", "provider_ledger", "put"])
def test_approval_numeric_equality_cannot_accept_invalid_types(field, value, source):
    scope, records = trace(200001)
    for record in records:
        if source != "all" and record["source"] != source:
            continue
        response_body = record["payload"].get("response", {}).get("body", {})
        if isinstance(response_body.get("approval"), dict):
            response_body["approval"][field] = value
        if record["source"] == "provider_ledger":
            response_body["entries"][0]["approval"][field] = value
    original = deepcopy(records)
    result = derive(scope, records)
    assert result["verdict"] == "fail"
    assert any(
        c["rule_id"] in {"APPROVAL_001", "STATE_001"}
        and c["verdict"] == "fail"
        and c["attribution"] == "product_defect"
        for c in result["checks"]
    )
    assert [r["payload"] for r in records] == [r["payload"] for r in original]


def test_integer_approval_baseline_remains_valid():
    scope, records = trace(200001)
    assert derive(scope, records)["verdict"] == "pass"
