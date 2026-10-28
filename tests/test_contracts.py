from copy import deepcopy

import pytest
from pydantic import ValidationError

from packages.contracts.config import ConfigSyntaxError, Configuration, Money, parse_yaml
from tests.conftest import EXAMPLE_PATH


def test_appendix_b_parses():
    config = parse_yaml(EXAMPLE_PATH.read_text())
    assert config.schema_version == "0.2"
    assert config.environment.approval_threshold_minor == 200000
    assert config.environment.threshold_operator == "gt"
    assert config.product.observations.provider_ledger == "required"
    assert [r.id for r in config.rules] == [
        "REFUND_001",
        "REFUND_002",
        "APPROVAL_001",
        "STATE_001",
        "TIME_001",
    ]


@pytest.mark.parametrize(
    "path",
    [
        "product.observations.provider_ledger",
        "product.observations.product_query",
        "product.observations.webhook",
        "actors.customer",
        "actors.support",
        "actors.approver",
        "product.credentials.support",
        "product.credentials.approver",
        "product.actions.approve_refund",
    ],
)
def test_missing_required_field(config_data, path):
    parts = path.split(".")
    target = config_data
    for part in parts[:-1]:
        target = target[part]
    del target[parts[-1]]
    with pytest.raises(ValidationError) as error:
        Configuration.model_validate(config_data)
    assert any(e["loc"] == tuple(parts) and e["type"] == "missing" for e in error.value.errors())


@pytest.mark.parametrize("field", ["max_events", "max_wall_seconds", "max_concurrency", "max_action_retries"])
@pytest.mark.parametrize("value", [-1, 1.5, "10", True])
def test_runtime_budget_requires_valid_integer(config_data, field, value):
    config_data["runtime"][field] = value
    with pytest.raises(ValidationError):
        Configuration.model_validate(config_data)


@pytest.mark.parametrize(
    "section,field", [("llm", "max_calls"), ("llm", "max_tokens"), ("artifacts", "raw_retention_days")]
)
def test_other_negative_budgets(config_data, section, field):
    config_data[section][field] = -1
    with pytest.raises(ValidationError):
        Configuration.model_validate(config_data)


@pytest.mark.parametrize("mode", ["controlled", "time_travel", "input"])
def test_unsupported_time_mode(config_data, mode):
    config_data["runtime"]["time_mode"] = mode
    with pytest.raises(ValidationError, match="time_mode"):
        Configuration.model_validate(config_data)


def test_declared_clock_capability(config_data):
    config_data["product"]["clock_support"] = ["realtime"]
    with pytest.raises(ValidationError, match="clock_support"):
        Configuration.model_validate(config_data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(unknown=1),
        lambda c: c["runtime"].update(max_event=1),
        lambda c: c["rules"][0]["params"].update(assertion="eval('x')"),
        lambda c: c["rules"][0].update(id="RUN_PYTHON"),
        lambda c: c["rules"][0].update(version="2"),
        lambda c: c["rules"].append(deepcopy(c["rules"][0])),
        lambda c: c["rules"][0]["params"].update(max_success_per_command=2),
        lambda c: c["gate"].update(required_checks=["REFUND_001"]),
        lambda c: c["product"]["observations"].update(provider_ledger="optional"),
        lambda c: c["product"]["credentials"].update(approver=c["product"]["credentials"]["support"]),
        lambda c: c["product"]["credentials"].update(support="raw-password-for-negative-test"),
        lambda c: c["product"]["actions"]["request_refund"].update(semantic="execute_money"),
        lambda c: c["rules"][1]["params"].update(currency="USD"),
        lambda c: c["rules"][2]["params"].update(threshold_minor=199999),
        lambda c: c["artifacts"].update(redact_secrets=False),
        lambda c: c["llm"].update(enabled=True),
    ],
)
def test_fail_closed_configuration(config_data, mutate):
    mutate(config_data)
    with pytest.raises(ValidationError):
        Configuration.model_validate(config_data)


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/test",
        "http://user:password@example.test",
        "http://example.test?secret=x",
        "http://example.test/#fragment",
    ],
)
def test_url_cannot_contain_inline_secrets(config_data, url):
    config_data["product"]["base_url"] = url
    with pytest.raises(ValidationError):
        Configuration.model_validate(config_data)


@pytest.mark.parametrize(
    "yaml", ["x: 1\nx: 2", "x: &a [*a]", "!!python/object/apply:os.system ['exit 1']", "x: [", "x" * 131073]
)
def test_unsafe_or_ambiguous_yaml(yaml):
    with pytest.raises(ConfigSyntaxError):
        parse_yaml(yaml)


def test_hash_is_canonical_and_content_sensitive(config_data):
    first = Configuration.model_validate(config_data)
    reordered = Configuration.model_validate(dict(reversed(list(config_data.items()))))
    assert first.content_hash() == reordered.content_hash()
    config_data["runtime"]["seed"] += 1
    assert first.content_hash() != Configuration.model_validate(config_data).content_hash()
    assert len(first.content_hash()) == 64


@pytest.mark.parametrize("amount", [-1, 1.5, "100", True])
def test_money_is_integer_minor_units(amount):
    with pytest.raises(ValidationError):
        Money(amount_minor=amount, currency="CNY")


def test_explicit_currency():
    assert Money(amount_minor=5000, currency="CNY").amount_minor == 5000
    with pytest.raises(ValidationError):
        Money(amount_minor=5000, currency="UNKNOWN")


@pytest.mark.parametrize("version", ["0.1", "1.0"])
def test_unsupported_schema_version_is_not_silently_upgraded(config_data, version):
    config_data["schema_version"] = version
    with pytest.raises(ValidationError, match="schema_version"):
        Configuration.model_validate(config_data)


def test_exported_schema_matches_versioned_model():
    import json
    from pathlib import Path

    assert (
        json.loads(Path("packages/contracts/schema.v0.2.json").read_text())
        == Configuration.model_json_schema()
    )
