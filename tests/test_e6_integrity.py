"""E6 migration, immutable assets, strict mode requests and live semantic fault matching."""

from uuid import uuid4

import pytest
from alembic import command
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from packages.contracts.replay import ReplayInput
from packages.transport.security import Scope, canonical, digest, headers
from tests.conftest import temporary_database
from tests.test_e5_live import save
from tests.test_e6_live import compare, get, replay, setup_project
from tests.test_migrations import seed_run


def test_e6_populated_e5_migration_preserves_old_contract_and_manifest(config_data):
    with temporary_database() as (db, migration):
        command.upgrade(migration, "0004_e5")
        scope = seed_run(db, config_data)
        old = {"schema_version": "e5-schedule-1", "original": True}
        with db.begin() as c:
            c.execute(
                text("INSERT INTO manifests VALUES (:p,:r,:hash,CAST(:v AS jsonb))"),
                scope | {"hash": digest(old), "v": canonical(old)},
            )
        command.upgrade(migration, "head")
        command.upgrade(migration, "head")
        with db.begin() as c:
            c.execute(
                text("INSERT INTO replay_assets VALUES (:p,:r,'actors',:hash,'[]')"),
                scope | {"hash": digest([])},
            )
            c.execute(
                text(
                    "INSERT INTO replay_seals(project_id,run_id,parent_hash,content_hash,payload) VALUES (:p,:r,:h,:h,'{}')"
                ),
                scope,
            )
        for table in ("replay_assets", "replay_seals"):
            for operation in ("UPDATE " + table + " SET payload='{}'", "DELETE FROM " + table):
                with pytest.raises(IntegrityError, match="immutable record"):
                    with db.begin() as c:
                        c.execute(text(operation + " WHERE project_id=:p AND run_id=:r"), scope)
        command.downgrade(migration, "0004_e5")
        command.upgrade(migration, "head")
        with db.connect() as c:
            assert (
                c.execute(
                    text("SELECT payload FROM manifests WHERE project_id=:p AND run_id=:r"), scope
                ).scalar_one()
                == old
            )
            assert (
                c.execute(text("SELECT content_hash FROM contracts WHERE project_id=:p"), scope).scalar_one()
                == scope["h"]
            )
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0007_e9"


@pytest.mark.parametrize("value", [True, 1, "false", "true"])
def test_replay_reuse_flag_cannot_coerce_or_enable(value):
    with pytest.raises(ValidationError):
        ReplayInput(
            project_id=uuid4(),
            mode="input",
            target_contract_version="fixed",
            target_product_version="fixed",
            idempotency_key="a",
            reuse_product_outputs=value,
        )


def test_provider_semantic_fixture_mismatch_and_first_eligible_call(live_stack):
    http = live_stack["http"]
    scope = Scope(project_id=uuid4(), run_id=uuid4())
    endpoint = "http://127.0.0.1:8002"
    seed = {
        "payments": [{"payment_id": "p1", "amount_minor": 50000, "currency": "CNY"}],
        "binding_id": str(uuid4()),
    }
    assert (
        http.post(endpoint + "/test/seed", json=seed, headers=headers("provider_admin", scope)).status_code
        == 200
    )
    fields = {
        "payment_id": "p1",
        "amount_minor": 10000,
        "currency": "CNY",
        "recipient": "demo-recipient",
        "command_version": 1,
    }
    plan = {
        "fault_id": "semantic-rate",
        "behavior": "rate_limit",
        "command_id": "r1",
        "attempt": 1,
        "times": 1,
        "duration_ms": 50,
        "semantic": {"operation": "execute_payment", "fields": fields, "state": "uncommitted"},
    }
    assert (
        http.post(endpoint + "/test/faults", json=plan, headers=headers("provider_admin", scope)).status_code
        == 200
    )
    request = fields | {"refund_command_id": "r1", "idempotency_key": "k1"}
    bad = http.post(
        endpoint + "/executions",
        json=request | {"amount_minor": 9000},
        headers=headers("provider_execute", scope),
    )
    assert bad.status_code == 409 and bad.json()["error"] == "fixture_mismatch"
    # This is request number two, but the FIRST request matching semantics and pre-state.
    eligible = http.post(endpoint + "/executions", json=request, headers=headers("provider_execute", scope))
    assert eligible.status_code == 429
    last = http.post(endpoint + "/executions", json=request, headers=headers("provider_execute", scope))
    assert last.status_code == 200
    evidence = http.get(endpoint + "/test/evidence", headers=headers("provider_reader", scope)).json()
    hits = [r for r in evidence["records"] if r["kind"] == "fault_hit"]
    assert len(hits) == 1 and hits[0]["payload"]["attempt_actual"] == 2
    assert any(r["kind"] == "fixture_mismatch" for r in evidence["records"])
    ledger = http.get(endpoint + "/test/ledger", headers=headers("provider_reader", scope)).json()
    assert len(ledger["entries"]) == 1 and ledger["entries"][0]["amount_minor"] == 10000
    save("e6-provider-semantic-mismatch.json", {"records": evidence, "ledger": ledger})


@pytest.mark.parametrize("kind", ["actors", "faults", "snapshot"])
def test_removing_required_asset_after_pass_invalidates_live_verdict(live_stack, kind):
    http = live_stack["http"]
    source, _ = setup_project(http)
    before = get(http, source, "history")
    target, report, _ = replay(http, source)
    assert report["verdict"] == "pass"
    audit = uuid4()
    purpose = {"test": "required_asset_loss", "kind": kind}
    with live_stack["db"].begin() as c:
        c.execute(
            text(
                "INSERT INTO reset_audits(project_id,run_id,reset_id,payload,content_hash) VALUES (:p,:r,:id,CAST(:v AS jsonb),:h)"
            ),
            target.params | {"id": audit, "v": canonical(purpose), "h": digest(purpose)},
        )
        c.execute(text("SELECT set_config('simulation.reset_id',:id,true)"), {"id": str(audit)})
        c.execute(
            text("DELETE FROM replay_assets WHERE project_id=:p AND run_id=:r AND kind=:kind"),
            target.params | {"kind": kind},
        )
    changed = get(http, target, "report")
    assert changed["verdict"] == "inconclusive"
    assert "missing_or_corrupt_" + kind in changed["replay"]["issues"]
    result = compare(http, source, target)
    assert not result["repair_verified"] and result["integrity_issues"]["target"]
    assert get(http, source, "history") == before
    save("e6-asset-loss-" + kind + ".json", {"report": changed, "compare": result})
