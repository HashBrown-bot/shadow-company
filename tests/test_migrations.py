import json
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from packages.contracts.config import Configuration
from tests.conftest import temporary_database


def seed_run(engine, config_data):
    project_id, run_id = uuid4(), uuid4()
    config = Configuration.model_validate(config_data)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id,name,ownership,local_access_policy) VALUES (:id,'示例迁移测试','local_team','loopback_only')"
            ),
            {"id": project_id},
        )
        conn.execute(
            text(
                "INSERT INTO contracts (project_id,version,schema_version,content_hash,config) VALUES (:p,'v1','0.2',:h,CAST(:c AS jsonb))"
            ),
            {"p": project_id, "h": config.content_hash(), "c": config.canonical_json()},
        )
        conn.execute(
            text(
                "INSERT INTO runs (project_id,run_id,contract_version,contract_hash,put_version,seed,time_mode) VALUES (:p,:r,'v1',:h,'fixed',1,'realtime')"
            ),
            {"p": project_id, "r": run_id, "h": config.content_hash()},
        )
    return {"p": project_id, "r": run_id, "h": config.content_hash()}


def test_migration_empty_upgrade_repeat_downgrade_upgrade():
    with temporary_database() as (engine, config):
        assert inspect(engine).get_table_names() == []
        command.upgrade(config, "head")
        expected = {
            "projects",
            "contracts",
            "runs",
            "events",
            "actions",
            "observations",
            "check_results",
            "findings",
            "manifests",
            "jobs",
            "alembic_version",
            "run_inputs",
            "webhook_bindings",
            "webhook_receipts",
            "preflights",
            "reset_audits",
            "evaluations",
            "runtime_journal",
            "event_dispatches",
            "replay_assets",
            "replay_seals",
            "actor_policies",
            "actor_calls",
            "experiments",
            "experiment_runs",
            "finding_reviews",
            "private_evidence",
            "lifecycle_audits",
        }
        assert set(inspect(engine).get_table_names()) == expected
        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0007_e9"
        command.downgrade(config, "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
        command.upgrade(config, "0001_e2")
        # A populated E2 database upgrades without losing the immutable contract or illegal observations.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO projects (id,name,ownership,local_access_policy) VALUES (:id,'E2 preserved','local_team','loopback_only')"
                ),
                {"id": uuid4()},
            )
        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) == expected
        assert set(inspect(engine).get_table_names(schema="refund_put")) == {
            "audit",
            "fault_plans",
            "namespaces",
            "payments",
            "refunds",
            "receipts",
        }
        assert set(inspect(engine).get_table_names(schema="payment_provider")) == {
            "audit",
            "fault_plans",
            "namespaces",
            "payments",
            "ledger",
            "outbox",
        }
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM projects")).scalar_one() == 1


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE contracts SET version='changed' WHERE project_id=:p",
        "DELETE FROM contracts WHERE project_id=:p",
    ],
)
def test_referenced_contract_immutable_at_database_level(database, config_data, operation):
    scope = seed_run(database, config_data)
    with pytest.raises(IntegrityError, match="immutable record"):
        with database.begin() as conn:
            conn.execute(text(operation), scope)
    with database.connect() as conn:
        assert (
            conn.execute(
                text("SELECT contract_hash FROM runs WHERE project_id=:p AND run_id=:r"), scope
            ).scalar_one()
            == scope["h"]
        )


def test_foreign_keys_prevent_cross_project_and_wrong_hash(database, config_data):
    scope = seed_run(database, config_data)
    other = seed_run(database, config_data)
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(
                text("INSERT INTO jobs (project_id,run_id,job_id,idempotency_key) VALUES (:p,:r,:j,'cross')"),
                scope | {"p": other["p"], "j": uuid4()},
            )
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO runs (project_id,run_id,contract_version,contract_hash,put_version,seed,time_mode) VALUES (:p,:r,'v1',:h,'fixed',1,'realtime')"
                ),
                scope | {"r": uuid4(), "h": "0" * 64},
            )


def test_illegal_raw_values_are_persisted_and_append_only(database, config_data):
    scope = seed_run(database, config_data)
    raw = {"balance_minor": -700, "currency": "BROKEN", "status": "invalid_business_state"}
    with database.begin() as conn:
        conn.execute(
            text("""INSERT INTO observations (project_id,run_id,observation_id,source,external_id,evidence_kind,raw_ref,digest,captured_at,payload)
            VALUES (:p,:r,:o,'put','r1','product_observation','private://raw/r1',:h,now(),CAST(:payload AS jsonb))"""),
            scope | {"o": uuid4(), "payload": json.dumps(raw)},
        )
    with database.connect() as conn:
        assert (
            conn.execute(
                text("SELECT payload FROM observations WHERE project_id=:p AND run_id=:r"), scope
            ).scalar_one()
            == raw
        )
    for sql in [
        "UPDATE observations SET payload='{}' WHERE project_id=:p",
        "DELETE FROM observations WHERE project_id=:p",
    ]:
        with pytest.raises(IntegrityError, match="immutable record"):
            with database.begin() as conn:
                conn.execute(text(sql), scope)


def test_completed_lifecycle_does_not_change_verdict(database, config_data):
    scope = seed_run(database, config_data)
    with database.begin() as conn:
        conn.execute(text("UPDATE runs SET status='completed' WHERE project_id=:p AND run_id=:r"), scope)
        assert (
            conn.execute(
                text("SELECT verdict FROM runs WHERE project_id=:p AND run_id=:r"), scope
            ).scalar_one()
            == "inconclusive"
        )
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(text("UPDATE runs SET verdict='success' WHERE project_id=:p AND run_id=:r"), scope)


def test_job_lease_requires_owner_and_heartbeat(database, config_data):
    scope = seed_run(database, config_data)
    with pytest.raises(IntegrityError):
        with database.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO jobs (project_id,run_id,job_id,idempotency_key,state) VALUES (:p,:r,:j,:key,'leased')"
                ),
                scope | {"j": uuid4(), "key": uuid4().hex},
            )
