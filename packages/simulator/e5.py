"""Durable E5 input scheduler. No verdicts or PUT behavior flags are passed to rules."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from uuid import uuid4, uuid5

from sqlalchemy import text

from adapters.http.registry import RefundAdapter
from packages.simulator.e3 import contract, require
from packages.simulator.e4 import inputs as e4_inputs
from packages.simulator.jobs import journal
from packages.transport.http import BoundaryError
from packages.transport.security import canonical, digest

SCENARIOS = tuple(f"S{i:02}" for i in range(1, 21))
FAULTS = {
    "S11": "connection_failure",
    "S12": "commit_then_timeout",
    "S13": "webhook_duplicate",
    "S14": "webhook_reorder",
    "S15": "rate_limit",
    "S18": "approver_offline",
}


def inputs(scenarios, config):
    plan = e4_inputs([s for s in scenarios if s in SCENARIOS[:10]])
    plan["faults"] = []

    def add(s, op, rid, body=None, role="support", **extra):
        step = {"scenario_id": s, "operation": op, "command_id": rid, "body": body, "role": role} | extra
        plan["steps"].append(step)
        if rid not in plan["commands"]:
            plan["commands"].append(rid)
        if rid not in plan["scenario_objects"].setdefault(s, []):
            plan["scenario_objects"][s].append(rid)

    for s in scenarios:
        if s in SCENARIOS[:10]:
            continue
        pid, rid = "payment-" + s, "refund-" + s
        plan["payments"].append(
            {"payment_id": pid, "amount_minor": 10000 if s == "S17" else 1000000, "currency": "CNY"}
        )
        commands = (
            [(rid + "-a", 6000), (rid + "-b", 5000)]
            if s == "S17"
            else [(rid + "-before", 10000), (rid + "-after", 10000)]
            if s == "S20"
            else [(rid, 200001 if s == "S18" else 10000)]
        )
        for name, amount in commands:
            add(
                s,
                "request_refund",
                name,
                {
                    "refund_command_id": name,
                    "payment_id": pid,
                    "amount_minor": amount,
                    "currency": "CNY",
                    "recipient": "demo-recipient",
                },
            )
        if s in FAULTS:
            configured = next((f for f in config.faults if f.match.scenario_id == s), None)
            behavior = configured.behavior if configured else FAULTS[s]
            plan["faults"].append(
                {
                    "fault_id": configured.id if configured else s + "-" + behavior,
                    "behavior": behavior,
                    "command_id": rid,
                    "attempt": configured.match.attempt if configured else 1,
                    "times": 1,
                    "duration_ms": 1000 if s == "S18" else 50 if s == "S15" else 350 if s == "S12" else 0,
                }
            )
        if s == "S18":
            add(s, "approve_refund", rid, role="approver", wait_after=1.0)
            add(s, "execute_refund", rid)
        elif s == "S16":
            add(s, "execute_refund", rid, group="S16-same")
            add(s, "execute_refund", rid, group="S16-same")
        elif s == "S17":
            for name, _ in commands:
                add(s, "execute_refund", name, group="S17-balance")
        elif s == "S19":
            add(s, "execute_refund", rid, group="S19-cancel")
            add(s, "cancel_refund", rid, group="S19-cancel")
        elif s == "S20":
            add(s, "execute_refund", commands[0][0], interrupt="before_dispatch")
            add(s, "execute_refund", commands[1][0], interrupt="after_remote_before_ack")
        else:
            add(s, "execute_refund", rid)
            if s in {"S13", "S14"}:
                add(s, "read_refund", rid, delivery_after=FAULTS[s])
    return plan


def wire(step, config):
    op, rid = step["operation"], step["command_id"]
    if op == "amend_refund":
        return "PATCH", "/refunds/" + rid
    if op == "cancel_refund":
        return "POST", "/refunds/" + rid + "/cancel"
    endpoint = getattr(config.product.actions, op)
    return endpoint.method, endpoint.path.replace("{refund_id}", rid)


def schedule(config, plan, binding):
    events = []

    def call(target, role, method, path, body=None, **meta):
        events.append(
            {
                "target": target,
                "role": role,
                "method": method,
                "path": path,
                "body": body,
                "command_id": "protocol",
                "operation": "control",
            }
            | meta
        )

    seed = {"payments": plan["payments"], "binding_id": str(binding)}
    for target, role in [("provider", "provider_admin"), ("put", "put_admin")]:
        call(target, role, "POST", "/test/seed", seed)
    call("put", "put_admin", "POST", "/test/behavior", {"variant": config.product.version})
    for role in ("support", "approver", "customer_a", "customer_b"):
        call("put", role, "GET", "/identity")
    for fault in plan["faults"]:
        target = "put" if fault["behavior"] == "approver_offline" else "provider"
        call(target, "put_admin" if target == "put" else "provider_admin", "POST", "/test/faults", fault)
    seen = set()
    for step in plan["steps"]:
        group = step.get("group")
        if group and group not in seen:
            members = [s for s in plan["steps"] if s.get("group") == group]
            call(
                "put",
                "put_admin",
                "POST",
                "/test/barriers",
                {
                    "group_id": group,
                    "command_ids": list(dict.fromkeys(s["command_id"] for s in members)),
                    "parties": len(members),
                },
            )
            seen.add(group)
        method, path = wire(step, config)
        call(
            "put",
            step["role"],
            method,
            path,
            step["body"],
            **{k: v for k, v in step.items() if k not in {"role", "body"}},
        )
        if step.get("wait_after"):
            events.append(
                {"operation": "wait", "seconds": step["wait_after"], "command_id": step["command_id"]}
            )
        if step.get("delivery_after"):
            call(
                "provider",
                "provider_admin",
                "POST",
                "/test/deliver",
                {"command_id": step["command_id"], "behavior": step["delivery_after"]},
            )
            call(
                "put",
                "support",
                "GET",
                "/refunds/" + step["command_id"],
                operation="read_refund",
                command_id=step["command_id"],
            )
    call("provider", "provider_admin", "POST", "/test/deliver")
    window = next(r.params.observation_wall_seconds for r in config.rules if r.id == "TIME_001")
    events.append({"operation": "wait", "seconds": window, "command_id": "observation-window"})
    for rid in plan["commands"]:
        call("put", "support", "GET", "/refunds/" + rid, operation="read_refund", command_id=rid)
    call("provider", "provider_reader", "GET", config.provider.ledger_path)
    call("provider", "provider_reader", "GET", "/test/evidence")
    call("put", "put_admin", "GET", "/test/evidence")
    offset = 0
    previous = None
    for index, event in enumerate(events, 1):
        if not event.get("group") or event.get("group") != previous:
            offset += 10
        event["offset_ms"] = offset
        event["priority"] = 0
        event["sequence"] = index
        previous = event.get("group")
    return events


def freeze(c, scope, config, plan, binding, *, events=None, manifest=None):
    events = events if events is not None else schedule(config, plan, binding)
    origin = datetime(2000, 1, 1, tzinfo=timezone.utc)
    parent = None
    group_parent = None
    previous_group = None
    for spec in events:
        eid = uuid5(scope.run_id, "event:" + str(spec["sequence"]))
        group = spec.get("group")
        if not group or group != previous_group:
            group_parent = parent
        causal_parent = group_parent if group else parent
        previous_group = group
        c.execute(
            text(
                "INSERT INTO events(project_id,run_id,event_id,parent_id,causation_id,business_object_id,simulation_time,wall_time,ingress_sequence,payload,priority) VALUES (:p,:r,:e,:parent,:parent,:obj,:sim,clock_timestamp(),:seq,CAST(:v AS jsonb),:priority)"
            ),
            scope.params
            | {
                "e": eid,
                "parent": causal_parent,
                "obj": spec["command_id"],
                "sim": origin + timedelta(milliseconds=spec["offset_ms"]),
                "seq": spec["sequence"],
                "v": canonical(spec),
                "priority": spec["priority"],
            },
        )
        c.execute(
            text("INSERT INTO event_dispatches(project_id,run_id,event_id) VALUES (:p,:r,:e)"),
            scope.params | {"e": eid},
        )
        parent = eid
    manifest = manifest or {
        "schema_version": "e5-schedule-1",
        "scope": scope.model_dump(mode="json"),
        "contract_hash": config.content_hash(),
        "input_hash": digest(plan),
        "schedule_hash": digest(events),
        "fault_plan": plan["faults"],
        "time_mode": config.runtime.time_mode,
        "external_clock_control": False,
        "replay_capability": "unavailable",
        "event_count": len(events),
    }
    c.execute(
        text("INSERT INTO manifests VALUES (:p,:r,:h,CAST(:v AS jsonb))"),
        scope.params | {"h": digest(manifest), "v": canonical(manifest)},
    )
    c.execute(
        text("UPDATE runs SET manifest_hash=:h WHERE project_id=:p AND run_id=:r"),
        scope.params | {"h": digest(manifest)},
    )


def interrupt_once(db, scope, event, position):
    if event["payload"].get("interrupt") != position:
        return
    if os.environ.get("EXAMPLE_TEST_MODE") != "1":
        raise BoundaryError("worker_interrupt_requires_test_mode")
    with db.begin() as c:
        exists = c.execute(
            text(
                "SELECT 1 FROM runtime_journal WHERE project_id=:p AND run_id=:r AND event_id=:e AND kind='worker_interrupted'"
            ),
            scope.params | {"e": event["event_id"]},
        ).scalar()
        if exists:
            return
        journal(c, scope, "worker_interrupted", {"position": position, "pid": os.getpid()}, event["event_id"])
    os._exit(86)  # Abrupt child-worker exit: no finally, ack, lease release or graceful cleanup.


def execute_run(db, lease):
    scope = lease.scope
    with db.connect() as c:
        version = c.execute(
            text("SELECT contract_version FROM runs WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()
        data = c.execute(
            text("SELECT payload FROM run_inputs WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()
    plan = data["plan"]
    config, _ = contract(db, scope.project_id, version)
    adapter = RefundAdapter(db, scope, config)
    actor_policy = None
    if data.get("request", {}).get("actor_policy") is not None:
        from packages.simulator.actors import load_policy

        actor_policy = load_policy(db, scope)
    guard = None
    if data.get("kind") == "e6_replay":
        from packages.simulator.replay import ReplayGuard

        guard = ReplayGuard(db, scope, adapter)

    def wait(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            lease.check(config)
            Event().wait(min(0.05, max(0, end - time.monotonic())))

    def perform(event, barrier=None):
        generator_started = time.monotonic()
        cpu_started = time.thread_time()
        spec = event["payload"]
        eid = event["event_id"]
        interrupt_once(db, scope, event, "before_dispatch")
        # Budget, cancellation and lease ownership share the dispatch linearization lock.
        with db.begin() as c:
            row = lease.row(c)
            if row["cancel_requested"]:
                raise BoundaryError("cancelled")
            used = row["checkpoint"].get("events_used", 0)
            elapsed = (row["db_now"] - row["started_at"]).total_seconds()
            if used >= config.runtime.max_events or elapsed >= config.runtime.max_wall_seconds:
                raise BoundaryError("budget_exhausted")
            state = c.execute(
                text(
                    "SELECT state FROM event_dispatches WHERE project_id=:p AND run_id=:r AND event_id=:e FOR UPDATE"
                ),
                scope.params | {"e": eid},
            ).scalar_one()
            if state == "done":
                return
            if state != "pending":
                raise BoundaryError("remote_outcome_unknown")
            c.execute(
                text(
                    "UPDATE event_dispatches SET state='inflight',lease_epoch=:epoch,attempts=attempts+1 WHERE project_id=:p AND run_id=:r AND event_id=:e"
                ),
                scope.params | {"e": eid, "epoch": lease.epoch},
            )
            seq = journal(
                c,
                scope,
                "dispatch_started",
                {
                    "lease_epoch": lease.epoch,
                    "group": spec.get("group"),
                    "operation": spec["operation"],
                    "simulation_time": event["simulation_time"],
                },
                eid,
            )
            action_id = uuid4()
            c.execute(
                text(
                    "INSERT INTO actions(project_id,run_id,action_id,event_id,actor_id,operation,request_ref,start_time,start_sequence) VALUES (:p,:r,:a,:e,:actor,:op,:ref,clock_timestamp(),:seq)"
                ),
                scope.params
                | {
                    "a": action_id,
                    "e": eid,
                    "actor": spec.get("role", "scheduler"),
                    "op": spec["operation"],
                    "ref": "private://pending/" + str(eid),
                    "seq": seq,
                },
            )
            checkpoint = row["checkpoint"] | {
                "events_used": used + 1,
                "last_dispatched": str(eid),
                "wall_seconds": elapsed,
                "llm_calls": row["checkpoint"].get("llm_calls", 0),
                "llm_tokens": row["checkpoint"].get("llm_tokens", 0),
            }
            c.execute(
                text("UPDATE jobs SET checkpoint=CAST(:v AS jsonb) WHERE project_id=:p AND run_id=:r"),
                scope.params | {"v": canonical(checkpoint)},
            )
        skipped = guard.before(event) if guard else False
        if actor_policy:
            from packages.simulator.actors import record_rule_route

            record_rule_route(db, lease, event, actor_policy)
        if barrier:
            try:
                barrier.wait(timeout=4)
            except Exception:
                raise BoundaryError("barrier_incomplete") from None
        with db.begin() as c:
            journal(
                c,
                scope,
                "generator_dispatch_timing",
                {
                    "preparation_ms": round((time.monotonic() - generator_started) * 1000, 3),
                    "cpu_ms": round((time.thread_time() - cpu_started) * 1000, 3),
                    "includes_barrier_wait": bool(barrier),
                },
                eid,
            )
        if skipped:
            result = {"status": None, "skipped_by_policy": True}
        elif spec["operation"] == "wait":
            wait(spec["seconds"])
            result = {"status": 200, "body": {"waited_wall_seconds": spec["seconds"]}}
        else:
            extra = {"X-Sim-Max-Retries": str(config.runtime.max_action_retries)}
            if spec.get("group"):
                extra["X-Sim-Barrier"] = spec["group"]
            result = adapter.call(
                spec["target"],
                spec["role"],
                spec["method"],
                spec["path"],
                spec.get("body"),
                spec["operation"],
                spec["command_id"],
                context={"event_id": eid, "action_id": action_id},
                extra_headers=extra,
                after_remote=lambda: interrupt_once(db, scope, event, "after_remote_before_ack"),
            )
            if guard:
                guard.after(event, result)
            if spec["operation"] == "control":
                require(result)
        with db.begin() as c:
            lease.row(c)
            c.execute(
                text(
                    "UPDATE event_dispatches SET state='done',result=CAST(:v AS jsonb) WHERE project_id=:p AND run_id=:r AND event_id=:e"
                ),
                scope.params
                | {
                    "e": eid,
                    "v": canonical(
                        {"http_status": result["status"], **({"skipped_by_policy": True} if skipped else {})}
                    ),
                },
            )
            seq = journal(c, scope, "dispatch_acknowledged", {"action_id": str(action_id)}, eid)
            c.execute(
                text(
                    "UPDATE actions SET end_time=COALESCE(end_time,clock_timestamp()),end_sequence=COALESCE(end_sequence,:seq) WHERE project_id=:p AND run_id=:r AND action_id=:a"
                ),
                scope.params | {"a": action_id, "seq": seq},
            )

    def recover(event):
        spec = event["payload"]
        eid = event["event_id"]
        safe = False
        if spec["operation"] == "execute_refund":
            query = adapter.call(
                "put", "support", "GET", "/refunds/" + spec["command_id"], external_id=spec["command_id"]
            )
            ledger = adapter.ledger()
            body = query.get("body", {})
            book = ledger.get("body", {})
            entries = [x for x in book.get("entries", []) if x["refund_command_id"] == spec["command_id"]]
            safe = (
                query["status"] == 200
                and ledger["status"] == 200
                and book.get("complete") is True
                and (
                    (
                        body.get("status") == "succeeded"
                        and bool(entries)
                        and body.get("provider_entry_id") in {e["entry_id"] for e in entries}
                    )
                    or (body.get("status") in {"cancelled", "rejected"} and not entries)
                )
            )
        elif spec["operation"] == "wait":
            # Wait can be safely repeated, but never skip an unobserved wall-clock window.
            wait(spec["seconds"])
            safe = True
        elif spec.get("method") == "GET":
            result = adapter.call(
                spec["target"], spec["role"], "GET", spec["path"], external_id=spec["command_id"]
            )
            safe = result["status"] == 200
        else:
            # A durable response can acknowledge a completed attempt, never mere end_time.
            with db.connect() as c:
                responses = (
                    c.execute(
                        text(
                            "SELECT o.payload FROM actions a JOIN observations o ON a.project_id=o.project_id AND a.run_id=o.run_id AND a.request_ref=(:prefix || o.observation_id::text) WHERE a.project_id=:p AND a.run_id=:r AND a.event_id=:e AND a.end_time IS NOT NULL"
                        ),
                        scope.params | {"e": eid, "prefix": "private://postgres/" + scope.namespace + "/"},
                    )
                    .scalars()
                    .all()
                )
                statuses = [p.get("response", {}).get("status") for p in responses]
                safe = any(
                    type(status) is int
                    and (status == 200 if spec["operation"] == "control" else 200 <= status < 500)
                    for status in statuses
                )
        with db.begin() as c:
            lease.row(c)
            journal(
                c,
                scope,
                "recovery_verified" if safe else "recovery_unknown",
                {"operation": spec["operation"], "command_id": spec["command_id"], "resent": False},
                eid,
            )
            c.execute(
                text(
                    "UPDATE event_dispatches SET state=:s WHERE project_id=:p AND run_id=:r AND event_id=:e"
                ),
                scope.params | {"e": eid, "s": "done" if safe else "unknown"},
            )
        if not safe:
            raise BoundaryError("remote_outcome_unknown")

    try:
        if guard:
            guard.validate()
        with db.connect() as c:
            pending = (
                c.execute(
                    text(
                        "SELECT e.*,d.state FROM events e JOIN event_dispatches d USING(project_id,run_id,event_id) WHERE e.project_id=:p AND e.run_id=:r AND d.state NOT IN ('done','cancelled') ORDER BY simulation_time,priority,ingress_sequence,event_id"
                    ),
                    scope.params,
                )
                .mappings()
                .all()
            )
        for event in pending:
            if event["state"] == "inflight":
                recover(event)
            elif event["state"] == "unknown":
                raise BoundaryError("remote_outcome_unknown")
        with db.connect() as c:
            queue = (
                c.execute(
                    text(
                        "SELECT e.* FROM events e JOIN event_dispatches d USING(project_id,run_id,event_id) WHERE e.project_id=:p AND e.run_id=:r AND d.state='pending' ORDER BY simulation_time,priority,ingress_sequence,event_id"
                    ),
                    scope.params,
                )
                .mappings()
                .all()
            )
        previous = 0
        index = 0
        while index < len(queue):
            event = queue[index]
            spec = event["payload"]
            lease.check(config)
            if config.runtime.time_mode == "realtime":
                wait(max(0, (spec["offset_ms"] - previous) / 1000))
            previous = spec["offset_ms"]
            group = spec.get("group")
            if group:
                members = []
                while index < len(queue) and queue[index]["payload"].get("group") == group:
                    members.append(queue[index])
                    index += 1
                if len(members) > config.runtime.max_concurrency:
                    raise BoundaryError("concurrency_budget_exhausted")
                barrier = Barrier(len(members))
                with ThreadPoolExecutor(max_workers=len(members)) as pool:
                    futures = [pool.submit(perform, e, barrier) for e in members]
                    for future in futures:
                        future.result()
            else:
                perform(event)
                index += 1
        lease.check(config)
        lease.finish("completed", "e6_scope_complete" if guard else "e5_scope_complete")
    except BoundaryError as error:
        # No new business dispatch. Bounded read-only drain retains consequences of accepted work.
        with db.begin() as c:
            journal(c, scope, "drain_started", {"reason": str(error)})
        drain_deadline = time.monotonic() + 3
        reads = [("put", "support", "/refunds/" + rid, rid) for rid in plan["commands"]] + [
            ("provider", "provider_reader", config.provider.ledger_path, "protocol"),
            ("provider", "provider_reader", "/test/evidence", "protocol"),
            ("put", "put_admin", "/test/evidence", "protocol"),
        ]
        for target, role, path, external_id in reads:
            remaining = drain_deadline - time.monotonic()
            if remaining <= 0:
                with db.begin() as c:
                    journal(c, scope, "drain_incomplete", {"reason": "three_second_drain_limit"})
                break
            try:
                adapter.call(target, role, "GET", path, external_id=external_id, timeout=min(0.5, remaining))
            except BoundaryError:
                pass
        lease.finish("cancelled" if str(error) == "cancelled" else "failed", str(error))
    from packages.evaluators.reporting import report

    report(db, scope)
