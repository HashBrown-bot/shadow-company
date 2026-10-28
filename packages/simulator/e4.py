"""Serial E4 scenarios; no fault scheduling, barriers, automatic recovery or replay."""

import json
import time
from threading import Event

from sqlalchemy import text

from adapters.http.registry import RefundAdapter
from packages.simulator.e3 import contract, require
from packages.transport.http import BoundaryError
from packages.transport.security import digest

SCENARIOS = tuple(f"S{i:02}" for i in range(1, 11))


def inputs(scenarios):
    """Inputs only. No verdict, expected-success or approval-required labels."""
    payments, steps, commands, mapping = [], [], [], {}

    def payment(name, amount=1000000, currency="CNY"):
        payments.append({"payment_id": name, "amount_minor": amount, "currency": currency})

    def step(scenario, operation, command, body=None, role="support"):
        steps.append(
            {
                "scenario_id": scenario,
                "operation": operation,
                "command_id": command,
                "body": body,
                "role": role,
            }
        )
        if command not in commands:
            commands.append(command)
        mapping.setdefault(scenario, [])
        if command not in mapping[scenario]:
            mapping[scenario].append(command)

    def create(s, rid, pid, amount, currency="CNY"):
        step(
            s,
            "request_refund",
            rid,
            {
                "refund_command_id": rid,
                "payment_id": pid,
                "amount_minor": amount,
                "currency": currency,
                "recipient": "demo-recipient",
            },
        )

    for s in scenarios:
        pid, rid = "payment-" + s, "refund-" + s
        payment(pid, 10000 if s in {"S06", "S07"} else 1000000)
        if s == "S01":
            for name, amount in [(rid, 199999), (rid + "-equal", 200000)]:
                create(s, name, pid, amount)
                step(s, "execute_refund", name)
        elif s in {"S02", "S03", "S04", "S09"}:
            create(s, rid, pid, 200001)
            if s in {"S02", "S04", "S09"}:
                step(s, "approve_refund", rid, role="support" if s == "S09" else "approver")
            if s == "S04":
                step(s, "amend_refund", rid, {"amount_minor": 250000})
            step(s, "execute_refund", rid)
            if s == "S04":
                # A new valid approval is tested in a separate command; the amended
                # command retains its rejection/stale-approval evidence unchanged.
                create(s, rid + "-renewed", pid, 250000)
                step(s, "approve_refund", rid + "-renewed", role="approver")
                step(s, "execute_refund", rid + "-renewed")
        elif s == "S05":
            create(s, rid, pid, 10000)
            step(s, "execute_refund", rid)
            create(s, rid, pid, 10000)
            step(s, "execute_refund", rid)
        elif s in {"S06", "S07"}:
            for suffix, amount in [("-a", 6000), ("-b", 4000 if s == "S06" else 5000)]:
                create(s, rid + suffix, pid, amount)
                step(s, "execute_refund", rid + suffix)
        elif s == "S08":
            payment(pid + "-usd", 1000000, "USD")
            create(s, rid + "-cny", pid, 10000)
            step(s, "execute_refund", rid + "-cny")
            create(s, rid + "-usd", pid + "-usd", 10000, "USD")
            step(s, "execute_refund", rid + "-usd")
            create(s, rid + "-mismatch", pid, 10000, "USD")
        elif s == "S10":
            create(s, rid, pid, 10000)
            step(s, "execute_refund", rid)
            step(s, "read_refund", rid, role="customer_a")
            step(s, "read_refund", rid, role="customer_b")
    return {"payments": payments, "steps": steps, "commands": commands, "scenario_objects": mapping}


def execute_run(db, scope):
    with db.connect() as c:
        run = (
            c.execute(text("SELECT * FROM runs WHERE project_id=:p AND run_id=:r"), scope.params)
            .mappings()
            .one()
        )
        data = c.execute(
            text("SELECT payload FROM run_inputs WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()
        binding = c.execute(
            text("SELECT binding_id FROM webhook_bindings WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()
    config, _ = contract(db, scope.project_id, run["contract_version"])
    plan = data["plan"]
    adapter = RefundAdapter(db, scope, config)
    started = time.monotonic()
    count = 0

    def budget(consume=True):
        nonlocal count
        if consume:
            count += 1
        with db.begin() as c:
            if c.execute(
                text("SELECT cancel_requested FROM jobs WHERE project_id=:p AND run_id=:r FOR UPDATE"),
                scope.params,
            ).scalar():
                raise BoundaryError("cancelled")
            c.execute(
                text("UPDATE jobs SET checkpoint=CAST(:v AS jsonb) WHERE project_id=:p AND run_id=:r"),
                scope.params
                | {
                    "v": json.dumps(
                        {
                            "events_used": min(count, config.runtime.max_events),
                            "attempted_events": count,
                            "wall_seconds": round(time.monotonic() - started, 3),
                            "llm_calls": 0,
                            "llm_tokens": 0,
                        }
                    )
                },
            )
        if count > config.runtime.max_events or time.monotonic() - started >= config.runtime.max_wall_seconds:
            raise BoundaryError("budget_exhausted")

    def call(*args, **kwargs):
        budget()
        return adapter.call(*args, **kwargs)

    seed = {"payments": plan["payments"], "binding_id": str(binding)}
    for target, role in [("provider", "provider_admin"), ("put", "put_admin")]:
        result = require(call(target, role, "POST", "/test/seed", seed))
        if result.get("snapshot_hash") != digest(seed):
            raise BoundaryError("seed_snapshot_mismatch")
    require(call("put", "put_admin", "POST", "/test/behavior", {"variant": config.product.version}))
    for role in ("support", "approver", "customer_a", "customer_b"):
        require(call("put", role, "GET", "/identity"))
    for step in plan["steps"]:
        budget()
        if step["operation"] == "amend_refund":
            adapter.call(
                "put",
                step["role"],
                "PATCH",
                "/refunds/" + step["command_id"],
                step["body"],
                "amend_refund",
                step["command_id"],
            )
        else:
            adapter.action(step["operation"], step["command_id"], step["body"], step["role"])
    require(call("provider", "provider_admin", "POST", "/test/deliver"))
    window = next(r.params.observation_wall_seconds for r in config.rules if r.id == "TIME_001")
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        budget(False)
        Event().wait(min(0.05, max(0, deadline - time.monotonic())))
    for rid in plan["commands"]:
        budget()
        adapter.action("read_refund", rid)
    budget()
    require(adapter.ledger())
    budget(False)
    with db.begin() as c:
        c.execute(
            text(
                "UPDATE runs SET status='completed',stop_reason='e4_scope_complete' WHERE project_id=:p AND run_id=:r"
            ),
            scope.params,
        )
        c.execute(
            text("UPDATE jobs SET checkpoint=CAST(:v AS jsonb) WHERE project_id=:p AND run_id=:r"),
            scope.params
            | {
                "v": json.dumps(
                    {
                        "events_used": count,
                        "wall_seconds": round(time.monotonic() - started, 3),
                        "llm_calls": 0,
                        "llm_tokens": 0,
                    }
                )
            },
        )
    from packages.evaluators.reporting import report

    result = report(db, scope)
    with db.begin() as c:
        c.execute(
            text("UPDATE runs SET verdict=:v WHERE project_id=:p AND run_id=:r"),
            scope.params | {"v": result["verdict"]},
        )
