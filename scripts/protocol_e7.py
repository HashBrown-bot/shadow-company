"""Explicit OFFLINE model protocol probe for persistence/restart acceptance, not a PUT experiment."""

from uuid import uuid4

from sqlalchemy import text

from adapters.llm.protocol import ProtocolTestAdapter
from packages.contracts.actors import ActorPolicy
from packages.simulator.actors import ActorController, ActorIdentity, freeze_policy
from packages.simulator.e3 import contract, new_run
from packages.simulator.jobs import Lease
from packages.transport.security import Scope


def snapshot(db, scope):
    result = {
        "test_kind": "protocol_test_double",
        "real_model_service": "not_run",
        **scope.model_dump(mode="json"),
    }
    with db.connect() as c:
        for table in ("runs", "actor_policies", "actor_calls", "jobs"):
            result[table] = [
                dict(r)
                for r in c.execute(
                    text(f"SELECT * FROM {table} WHERE project_id=:p AND run_id=:r"), scope.params
                ).mappings()
            ]
    result["actor_calls"].sort(key=lambda r: (r["created_at"], str(r["call_id"]), r["phase"]))
    return result


def demonstrate(db, project_id):
    config, _ = contract(db, project_id, "fixed")
    scope = Scope(project_id=project_id, run_id=uuid4())
    policy = ActorPolicy(
        mode="hybrid",
        model_enabled=True,
        adapter="protocol_test",
        model_id="protocol-test/actions-v1",
        budget={"max_calls": 2, "max_tokens": 100000, "min_call_interval_ms": 0},
    )
    owner = "protocol-probe-" + uuid4().hex
    key = "worker:" + scope.namespace
    guard = db.connect()
    guard.execute(text("SELECT pg_advisory_lock(hashtextextended(:k,0))"), {"k": key})
    guard.commit()
    lease = Lease(db, scope, owner, 1, guard, key)
    try:
        with db.begin() as c:
            new_run(
                c,
                scope,
                "fixed",
                config,
                {"kind": "e7_protocol_test_only", "request": {"idempotency_key": uuid4().hex}},
            )
            freeze_policy(c, scope, policy)
            # Claim this synthetic probe atomically; the normal Worker must not execute it as a PUT suite.
            c.execute(
                text("""INSERT INTO jobs(project_id,run_id,job_id,idempotency_key,state,owner,lease_epoch,heartbeat,expires_at,started_at)
                VALUES (:p,:r,:id,:key,'leased',:owner,1,clock_timestamp(),clock_timestamp()+interval '30 seconds',clock_timestamp())"""),
                scope.params | {"id": uuid4(), "key": uuid4().hex, "owner": owner},
            )
            c.execute(
                text("UPDATE runs SET status='running' WHERE project_id=:p AND run_id=:r"), scope.params
            )
        adapter = ProtocolTestAdapter(
            [
                {"role": "support", "tool": "provider_ledger", "arguments": {}},
                {"role": "support", "tool": "read_refund", "arguments": {"command_id": "protocol-object"}},
            ]
        )
        action = ActorController(db, lease, config, adapter).decide(
            ActorIdentity(scope, "support", ("protocol-object",)), natural_language=True
        )
        assert action.tool == "read_refund" and len(adapter.requests) == 2
        # No product dispatch. This protocol-only probe cannot prove a business pass.
        lease.finish("completed", "protocol_test_only_no_business_verdict")
        result = snapshot(db, scope)
        assert result["runs"][0]["verdict"] == "inconclusive"
        return scope, result
    finally:
        lease.close()
