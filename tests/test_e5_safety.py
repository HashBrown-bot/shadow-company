"""Lease/migration and unknown-dispatch counterexamples, using real PostgreSQL."""

from uuid import uuid4

import pytest
from alembic import command
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from packages.contracts.config import Configuration
from packages.simulator.e3 import new_run
from packages.simulator.e5 import freeze, inputs
from packages.simulator.jobs import cancel, claim
from packages.transport.http import BoundaryError
from packages.transport.security import Scope, canonical
from tests.conftest import temporary_database
from tests.test_e5_live import config_for
from tests.test_migrations import seed_run


def job(db):
    config = Configuration.model_validate(config_for())
    scope = Scope(project_id=uuid4(), run_id=uuid4())
    plan = inputs(["S01"], config)
    with db.begin() as c:
        c.execute(
            text(
                "INSERT INTO projects(id,name,ownership,local_access_policy) VALUES (:p,'E5 safety','local_team','loopback_only')"
            ),
            scope.params,
        )
        c.execute(
            text("INSERT INTO contracts VALUES (:p,'e5','0.2',:h,CAST(:v AS jsonb),now())"),
            scope.params | {"h": config.content_hash(), "v": config.canonical_json()},
        )
        binding = new_run(
            c, scope, "e5", config, {"kind": "e5_runtime", "plan": plan, "request": {"scenarios": ["S01"]}}
        )
        freeze(c, scope, config, plan, binding)
        c.execute(
            text("INSERT INTO jobs(project_id,run_id,job_id,idempotency_key) VALUES (:p,:r,:j,:k)"),
            scope.params | {"j": uuid4(), "k": uuid4().hex},
        )
    return scope, config


def test_populated_e4_upgrade_hashes_raw_evidence_and_downgrade(config_data):
    with temporary_database() as (db, alembic):
        command.upgrade(alembic, "0003_e4")
        scope = seed_run(db, config_data)
        with db.begin() as c:
            c.execute(
                text(
                    "INSERT INTO observations VALUES (:p,:r,:o,'put','invalid','product_observation','private://old',:h,now(),'{\"amount_minor\":-1}')"
                ),
                scope | {"o": uuid4()},
            )
            c.execute(
                text(
                    "INSERT INTO jobs(project_id,run_id,job_id,idempotency_key,checkpoint) VALUES (:p,:r,:j,'old',CAST(:v AS jsonb))"
                ),
                scope | {"j": uuid4(), "v": canonical({"events_used": 3})},
            )
        command.upgrade(alembic, "head")
        command.upgrade(alembic, "head")
        with db.connect() as c:
            assert (
                c.execute(text("SELECT content_hash FROM contracts WHERE project_id=:p"), scope).scalar()
                == scope["h"]
            )
            assert c.execute(
                text("SELECT payload FROM observations WHERE project_id=:p AND run_id=:r"), scope
            ).scalar() == {"amount_minor": -1}
            old = (
                c.execute(text("SELECT * FROM jobs WHERE project_id=:p AND run_id=:r"), scope)
                .mappings()
                .one()
            )
            assert old["checkpoint"] == {"events_used": 3} and old["lease_epoch"] == 0
        command.downgrade(alembic, "0003_e4")
        command.upgrade(alembic, "head")
        with db.connect() as c:
            assert c.execute(text("SELECT count(*) FROM observations")).scalar() == 1


def test_session_lock_fences_expired_owner_and_epoch_rejects_stale_writer():
    with temporary_database() as (db, alembic):
        command.upgrade(alembic, "head")
        scope, config = job(db)
        first = claim(db)
        assert first is not None
        assert claim(db) is None
        with db.begin() as c:
            c.execute(
                text(
                    "UPDATE jobs SET expires_at=clock_timestamp()-interval '1 second' WHERE project_id=:p AND run_id=:r"
                ),
                scope.params,
            )
        # An expired lease cannot replace a process that still owns the remote-work lock.
        assert claim(db) is None
        assert first.heartbeat() is False
        with pytest.raises(BoundaryError, match="lease_lost"):
            first.check(config, True)
        first.close()
        second = claim(db)
        assert second.epoch == 2
        with pytest.raises(BoundaryError, match="lease_lost"):
            first.finish("completed", "must_not_commit")
        cancel(db, scope)
        with pytest.raises(BoundaryError, match="cancelled"):
            second.check(config, True)
        second.finish("cancelled", "cancelled")
        second.close()


def test_queued_cancel_dispatch_and_append_only_scoped_causation():
    with temporary_database() as (db, alembic):
        command.upgrade(alembic, "head")
        scope, config = job(db)
        assert cancel(db, scope)["cancel_requested"]
        assert claim(db) is None
        with db.connect() as c:
            assert (
                c.execute(
                    text("SELECT status FROM runs WHERE project_id=:p AND run_id=:r"), scope.params
                ).scalar()
                == "cancelled"
            )
        with pytest.raises(IntegrityError, match="immutable record"):
            with db.begin() as c:
                c.execute(
                    text("UPDATE runtime_journal SET payload='{}' WHERE project_id=:p AND run_id=:r"),
                    scope.params,
                )
        with pytest.raises(IntegrityError):
            with db.begin() as c:
                c.execute(
                    text(
                        "INSERT INTO events(project_id,run_id,event_id,causation_id,business_object_id,simulation_time,wall_time,ingress_sequence,payload) VALUES (:p,:r,:e,:cause,'out-of-scope',now(),now(),999,'{}')"
                    ),
                    scope.params | {"e": uuid4(), "cause": uuid4()},
                )


def test_unknown_non_idempotent_dispatch_never_reissued(live_stack):
    from adapters.http.refund import RefundAdapter
    from packages.simulator.e5 import execute_run
    from packages.transport.security import headers

    with temporary_database() as (db, alembic):
        command.upgrade(alembic, "head")
        scope, config = job(db)
        adapter = RefundAdapter(db, scope, config)
        with db.connect() as c:
            events = (
                c.execute(
                    text("SELECT * FROM events WHERE project_id=:p AND run_id=:r ORDER BY ingress_sequence"),
                    scope.params,
                )
                .mappings()
                .all()
            )
        # Reproduce the durable crash window after intent but before any execution receipt.
        execute = next(e for e in events if e["payload"]["operation"] == "execute_refund")
        for event in events:
            if event["ingress_sequence"] >= execute["ingress_sequence"]:
                break
            spec = event["payload"]
            response = adapter.call(
                spec["target"],
                spec["role"],
                spec["method"],
                spec["path"],
                spec.get("body"),
                external_id=spec["command_id"],
            )
            assert response["status"] in {200, 201}
            with db.begin() as c:
                c.execute(
                    text(
                        "UPDATE event_dispatches SET state='done' WHERE project_id=:p AND run_id=:r AND event_id=:e"
                    ),
                    scope.params | {"e": event["event_id"]},
                )
        with db.begin() as c:
            c.execute(
                text(
                    "UPDATE event_dispatches SET state='inflight',attempts=1 WHERE project_id=:p AND run_id=:r AND event_id=:e"
                ),
                scope.params | {"e": execute["event_id"]},
            )
        lease = claim(db)
        try:
            execute_run(db, lease)
        finally:
            lease.close()
        with db.connect() as c:
            assert (
                c.execute(
                    text("SELECT stop_reason FROM runs WHERE project_id=:p AND run_id=:r"), scope.params
                ).scalar()
                == "remote_outcome_unknown"
            )
            assert (
                c.execute(
                    text(
                        "SELECT state FROM event_dispatches WHERE project_id=:p AND run_id=:r AND event_id=:e"
                    ),
                    scope.params | {"e": execute["event_id"]},
                ).scalar()
                == "unknown"
            )
        result = (
            live_stack["http"]
            .get("http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope))
            .json()
        )
        assert result["entries"] == []
        audit = (
            live_stack["http"]
            .get("http://127.0.0.1:8002/test/evidence", headers=headers("provider_reader", scope))
            .json()
        )
        assert not any(r["kind"] == "execution_received" for r in audit["records"])


@pytest.mark.parametrize(
    "change",
    [
        {"boundary": "provider_connection", "behavior": "commit_then_timeout"},
        {"boundary": "provider_response", "behavior": "execute_python"},
    ],
)
def test_fault_config_rejects_wrong_boundary_or_executable_behavior(change):
    value = config_for()
    value["faults"] = [{"id": "invalid", "match": {"scenario_id": "S12", "attempt": 1}, **change}]
    with pytest.raises(ValidationError):
        Configuration.model_validate(value)
