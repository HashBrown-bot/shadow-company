"""Coverage of observed scheduling/fault boundaries, separate from business rules."""

from collections import defaultdict

from sqlalchemy import text

from packages.transport.security import digest, redact


def runtime_evidence(db, scope, inputs, observations):
    with db.connect() as c:
        events = [
            dict(x)
            for x in c.execute(
                text(
                    "SELECT e.*,d.state,d.attempts FROM events e JOIN event_dispatches d USING(project_id,run_id,event_id) WHERE project_id=:p AND run_id=:r ORDER BY simulation_time,priority,ingress_sequence"
                ),
                scope.params,
            ).mappings()
        ]
        actions = [
            dict(x)
            for x in c.execute(
                text(
                    "SELECT * FROM actions WHERE project_id=:p AND run_id=:r ORDER BY start_sequence,action_id"
                ),
                scope.params,
            ).mappings()
        ]
        journal = [
            dict(x)
            for x in c.execute(
                text("SELECT * FROM runtime_journal WHERE project_id=:p AND run_id=:r ORDER BY sequence"),
                scope.params,
            ).mappings()
        ]
    service_records = {}
    refs = {}
    for o in observations:
        p = o["payload"]
        if p.get("request", {}).get("path") != "/test/evidence" or o["digest"] != digest(p):
            continue
        response = p.get("response", {})
        body = response.get("body", {})
        if (
            response.get("status") != 200
            or body.get("project_id") != str(scope.project_id)
            or body.get("run_id") != str(scope.run_id)
        ):
            continue
        if o["source"] not in {"provider_control", "put"}:
            continue
        service_records[o["source"]] = body.get("records", [])
        refs[o["source"]] = str(o["observation_id"])
    hits = [r for records in service_records.values() for r in records if r["kind"] == "fault_hit"]
    plans = inputs.get("plan", {}).get("faults", [])
    fault_results = []
    for plan in plans:
        matching = [h for h in hits if all(h["payload"].get(k) == v for k, v in redact(plan).items())]
        valid = bool(matching)
        if plan["behavior"] == "commit_then_timeout":
            commits = [
                r for r in service_records.get("provider_control", []) if r["kind"] == "execution_committed"
            ]
            timeouts = [
                r
                for r in service_records.get("put", [])
                if r["kind"] == "provider_attempt"
                and r["payload"].get("command_id") == plan["command_id"]
                and r["payload"].get("outcome") == "read_timeout"
            ]
            valid = (
                valid
                and bool(timeouts)
                and any(
                    c["sequence"] < h["sequence"] and c["payload"]["entry_id"] == h["payload"].get("entry_id")
                    for c in commits
                    for h in matching
                )
            )
        if plan["behavior"] == "connection_failure":
            valid = valid and any(
                h["payload"].get("stage") == "before_commit" and h["payload"].get("entry_id") is None
                for h in matching
            )
            valid = valid and any(
                r["kind"] == "provider_attempt"
                and r["payload"].get("command_id") == plan["command_id"]
                and r["payload"].get("outcome") == "connection_failure"
                for r in service_records.get("put", [])
            )
        if plan["behavior"] in {"webhook_duplicate", "webhook_reorder"}:
            deliveries = [
                r
                for r in service_records.get("provider_control", [])
                if r["kind"] == "callback_delivery" and r["payload"].get("fault_id") == plan["fault_id"]
            ]
            valid = valid and {r["payload"]["receiver"] for r in deliveries} == {"put", "platform"}
            if plan["behavior"] == "webhook_duplicate":
                valid = valid and all(
                    r["payload"]["response"].get("body", {}).get("duplicate") is True for r in deliveries
                )
            else:
                valid = valid and all(
                    r["payload"].get("status") == "execution_pending"
                    and r["payload"].get("state_version") == 1
                    for r in deliveries
                )
        if plan["behavior"] == "rate_limit":
            calls = [
                r["payload"]
                for r in service_records.get("put", [])
                if r["kind"] == "provider_attempt" and r["payload"].get("command_id") == plan["command_id"]
            ]
            valid = (
                valid
                and any(x.get("status") == 429 for x in calls)
                and any(x.get("status") == 200 and x["attempt"] > 1 for x in calls)
            )
        if plan["behavior"] == "approver_offline":
            waits = [
                e
                for e in events
                if e["payload"]["operation"] == "wait"
                and e["payload"]["command_id"] == plan["command_id"]
                and e["state"] == "done"
            ]
            valid = valid and bool(waits)
        fault_results.append(
            {
                "fault_id": plan["fault_id"],
                "command_id": plan["command_id"],
                "behavior": plan["behavior"],
                "verified": valid,
                "hits": matching,
                "evidence_refs": list(refs.values()),
            }
        )
    groups = defaultdict(list)
    for event in events:
        if event["payload"].get("group"):
            groups[event["payload"]["group"]].append(event)
    concurrent = []
    for group, members in groups.items():
        ids = {e["event_id"] for e in members}
        calls = [a for a in actions if a["event_id"] in ids]
        complete = len(calls) == len(members) and all(a["end_time"] for a in calls)
        overlap = complete and max(a["start_time"] for a in calls) < min(a["end_time"] for a in calls)
        arrivals = [
            r
            for r in service_records.get("put", [])
            if r["kind"] == "barrier_arrived"
            and r["payload"].get("group_id") == group
            and r["payload"].get("phase") == "entry"
        ]
        releases = [
            r
            for r in service_records.get("put", [])
            if r["kind"] == "barrier_released"
            and r["payload"].get("group_id") == group
            and r["payload"].get("phase") == "entry"
        ]
        synchronized = (
            len(arrivals) == len(members)
            and len(releases) == len(members)
            and max(r["sequence"] for r in arrivals) < min(r["sequence"] for r in releases)
        )
        concurrent.append(
            {
                "group_id": group,
                "verified": bool(overlap and synchronized),
                "actual_overlap": bool(overlap),
                "event_sync": bool(synchronized),
                "actions": calls,
            }
        )
    recovered = {str(x["event_id"]) for x in journal if x["kind"] == "recovery_verified"}
    interruptions = [x for x in journal if x["kind"] == "worker_interrupted"]
    leases = [x for x in journal if x["kind"] == "lease_acquired"]
    recovery_ok = (
        len(interruptions) >= 2
        and len({x["payload"]["owner"] for x in leases}) >= 3
        and all(e["state"] == "done" for e in events if e["payload"].get("scenario_id") == "S20")
        and bool(recovered)
    )
    durations = [
        o["payload"]["response"].get("timing", {}).get("http_duration_ms")
        for o in observations
        if o["source"] == "put"
        and o["payload"].get("request", {}).get("path", "").startswith("/refunds")
        and "response" in o["payload"]
    ]
    durations = [x for x in durations if isinstance(x, (int, float))]
    return {
        "events": events,
        "actions": actions,
        "journal": journal,
        "fault_plan": plans,
        "faults": fault_results,
        "concurrency": concurrent,
        "recovered_event_ids": sorted(recovered),
        "worker_recovery_verified": recovery_ok,
        "performance": {
            "put_http_samples_ms": durations,
            "put_http_total_ms": round(sum(durations), 3),
            "put_http_measurement": "实际请求往返；含产品依赖等待，不是服务器 CPU 或吞吐量",
            "generator_preparation_ms": sum(
                j["payload"]["preparation_ms"] for j in journal if j["kind"] == "generator_dispatch_timing"
            ),
            "generator_cpu_ms": sum(
                j["payload"]["cpu_ms"] for j in journal if j["kind"] == "generator_dispatch_timing"
            ),
            "generator_dispatch_count": sum(x["kind"] == "dispatch_started" for x in journal),
            "generator_measurement": "run 墙钟和发生器开销另记；并发请求耗时不能相加当作吞吐量",
        },
    }


def scenario_verified(s, runtime):
    if s in {"S11", "S12", "S13", "S14", "S15", "S18"}:
        return any(f["command_id"] == "refund-" + s and f["verified"] for f in runtime["faults"])
    if s in {"S16", "S17", "S19"}:
        return any(g["group_id"].startswith(s + "-") and g["verified"] for g in runtime["concurrency"])
    if s == "S20":
        return runtime["worker_recovery_verified"]
    return True
