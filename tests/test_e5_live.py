"""E5 real HTTP, independent OS services, PostgreSQL and abrupt Worker child exits."""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import text

from packages.transport.security import Scope, headers
from tests.test_e4_live import BASE

ALL = tuple(f"S{i:02}" for i in range(1, 21))


def config_for(version="fixed", **runtime):
    config = yaml.safe_load(Path("environments/refund_approval/local.e5.yaml").read_text())
    config["product"]["version"] = version
    config["runtime"].update(runtime)
    return config


def start(http, scenarios=ALL, config=None):
    config = config or config_for()
    p = http.post(BASE + "/api/projects", json={"name": "E5 独立服务验收 " + uuid4().hex}).json()["id"]
    result = http.put(BASE + f"/api/projects/{p}/contract", json={"version": "e5-v1", "config": config})
    assert result.status_code == 200, result.text
    result = http.post(BASE + f"/api/projects/{p}/preflight", json={"contract_version": "e5-v1"})
    assert result.status_code == 200 and result.json()["passed"], result.text
    result = http.post(
        BASE + "/api/runs",
        json={
            "project_id": p,
            "contract_version": "e5-v1",
            "idempotency_key": uuid4().hex,
            "suite_scope": "e5_core_20",
            "scenarios": list(scenarios),
        },
    )
    assert result.status_code == 202, result.text
    return Scope(project_id=p, run_id=result.json()["run_id"])


def wait_report(http, scope):
    deadline = time.monotonic() + 45
    while True:
        run = http.get(
            BASE + f"/api/runs/{scope.run_id}", params={"project_id": str(scope.project_id)}
        ).json()
        if run["status"] in {"completed", "cancelled", "failed"}:
            response = http.get(
                BASE + f"/api/runs/{scope.run_id}/report", params={"project_id": str(scope.project_id)}
            )
            assert response.status_code == 200, response.text
            return response.json()
        assert time.monotonic() < deadline, run
        time.sleep(0.04)  # status polling only; concurrency itself uses barriers, never sleeps.


def save(name, value):
    directory = Path(os.environ.get("ACCEPTANCE_EVIDENCE_DIR", "docs/evidence/e5"))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))


@pytest.fixture(scope="module")
def fixed_e5(live_stack):
    scope = start(live_stack["http"])
    report = wait_report(live_stack["http"], scope)
    save("fixed-s01-s20.json", report)
    return scope, report


def test_all_twenty_real_scenarios_and_no_false_positives(fixed_e5):
    scope, report = fixed_e5
    assert report["status"] == "completed", report["stop_reason"]
    assert report["verdict"] == "pass", [
        (c["rule_id"], c["object_id"], c["reason"])
        for c in report["checks"]
        if c["verdict"] not in {"pass", "not_applicable"}
    ]
    assert len(report["coverage"]) == 20 and all(c["verdict"] == "pass" for c in report["coverage"]), report[
        "coverage"
    ]
    assert report["gate"]["verdict"] == "pass" and report["findings"] == []
    assert all(f["verified"] for f in report["runtime"]["faults"])
    assert len(report["runtime"]["faults"]) == 6
    assert len(report["runtime"]["concurrency"]) == 3
    assert all(g["actual_overlap"] and g["event_sync"] for g in report["runtime"]["concurrency"])
    assert report["runtime"]["performance"]["put_http_samples_ms"]
    assert report["runtime"]["performance"]["generator_wall_seconds"] > 0


def test_actual_process_restarts_checkpoint_and_no_duplicate_money(fixed_e5, live_stack):
    scope, report = fixed_e5
    runtime = report["runtime"]
    interrupted = [j for j in runtime["journal"] if j["kind"] == "worker_interrupted"]
    assert {j["payload"]["position"] for j in interrupted} == {"before_dispatch", "after_remote_before_ack"}
    assert len({j["payload"]["pid"] for j in interrupted}) == 2
    assert runtime["worker_recovery_verified"]
    assert all(e["state"] == "done" and e["attempts"] == 1 for e in runtime["events"])
    ledger = (
        live_stack["http"]
        .get("http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope))
        .json()
    )
    for rid in ["refund-S20-before", "refund-S20-after"]:
        assert len([e for e in ledger["entries"] if e["refund_command_id"] == rid]) == 1
    assert any(
        j["kind"] == "recovery_verified" and j["payload"]["resent"] is False for j in runtime["journal"]
    )
    # Intentional S16 duplicate calls survive platform event deduplication.
    repeated = [e for e in runtime["events"] if e["payload"].get("group") == "S16-same"]
    assert len({e["event_id"] for e in repeated}) == 2
    with live_stack["db"].connect() as c:
        assert c.execute(
            text("SELECT count(*) FROM event_dispatches WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar() == len(runtime["events"])


def test_buggy_timeout_race_and_stale_callback_from_actual_observations(live_stack):
    scope = start(
        live_stack["http"],
        ["S11", "S12", "S13", "S14", "S15", "S16", "S17", "S18", "S19"],
        config_for("buggy"),
    )
    report = wait_report(live_stack["http"], scope)
    save("buggy-e5.json", report)
    assert report["status"] == "completed", report["stop_reason"]
    assert report["verdict"] == "fail"
    failed = {(c["rule_id"], c["object_id"]) for c in report["checks"] if c["verdict"] == "fail"}
    assert ("REFUND_001", "refund-S12") in failed
    assert ("REFUND_001", "refund-S16") in failed
    assert ("REFUND_002", "refund-S17-a") in failed
    assert ("STATE_001", "refund-S14") in failed
    assert all(g["verified"] for g in report["runtime"]["concurrency"])
    assert all(f["verified"] for f in report["runtime"]["faults"])
    calls = (
        live_stack["http"]
        .get("http://127.0.0.1:8002/test/evidence", headers=headers("provider_reader", scope))
        .json()["records"]
    )
    commits = [
        r for r in calls if r["kind"] == "execution_committed" and r["payload"]["command_id"] == "refund-S12"
    ]
    assert len(commits) == 2


def test_cancel_after_provider_commit_keeps_inflight_consequences(live_stack):
    http = live_stack["http"]
    scope = start(http, ["S12", "S15"])
    deadline = time.monotonic() + 15
    while True:
        result = http.get("http://127.0.0.1:8002/test/evidence", headers=headers("provider_reader", scope))
        hits = result.json().get("records", [])
        if any(
            r["kind"] == "fault_hit" and r["payload"].get("stage") == "after_commit_response_withheld"
            for r in hits
        ):
            break
        assert time.monotonic() < deadline
        time.sleep(0.01)
    response = http.post(
        BASE + f"/api/runs/{scope.run_id}/cancel", params={"project_id": str(scope.project_id)}
    )
    assert response.status_code == 200 and response.json()["cancel_requested"]
    report = wait_report(http, scope)
    save("cancel-inflight.json", report)
    assert report["status"] == "cancelled" and report["verdict"] != "pass"
    journal = report["runtime"]["journal"]
    cancel = next(j for j in journal if j["kind"] == "cancel_requested")
    assert not any(j["kind"] == "dispatch_started" and j["sequence"] > cancel["sequence"] for j in journal)
    ledger = http.get("http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope)).json()
    assert len(ledger["entries"]) == 1 and ledger["entries"][0]["refund_command_id"] == "refund-S12"
    assert any(a["end_time"] for a in report["runtime"]["actions"] if a["operation"] == "execute_refund")


@pytest.mark.parametrize(
    "runtime,reason",
    [
        ({"max_events": 8}, "budget_exhausted"),
        ({"max_wall_seconds": 1}, "budget_exhausted"),
        ({"max_concurrency": 1}, "concurrency_budget_exhausted"),
    ],
)
def test_actual_budget_limits(live_stack, runtime, reason):
    scenario = ["S16"] if "max_concurrency" in runtime else ["S18"]
    scope = start(live_stack["http"], scenario, config_for(**runtime))
    report = wait_report(live_stack["http"], scope)
    assert report["status"] == "failed" and report["stop_reason"] == reason
    assert report["verdict"] != "pass" and report["gate"]["verdict"] != "pass"
    assert report["budget"]["used"]["events_used"] <= report["budget"]["limits"]["max_events"]
    for selection in ("selected", "suite"):
        assert report["ci_gates"][selection]["exit_code"] == 3
        assert report["ci_gates"][selection]["verdict"] == "inconclusive"
    save("budget-" + next(iter(runtime)) + ".json", report)


def test_realtime_and_compressed_keep_real_observation_window(live_stack):
    scopes = []
    for mode in ["realtime", "event_compressed"]:
        scope = start(live_stack["http"], ["S13"], config_for(time_mode=mode))
        report = wait_report(live_stack["http"], scope)
        assert report["verdict"] == "pass", report["evidence_issues"]
        events = report["runtime"]["events"]
        assert [e["ingress_sequence"] for e in events] == list(range(1, len(events) + 1))
        assert all(e["causation_id"] for e in events[1:])
        assert all(e["simulation_time"] != e["wall_time"] for e in events)
        waits = [a for a in report["runtime"]["actions"] if a["operation"] == "wait"]
        from datetime import datetime

        assert all(
            (datetime.fromisoformat(a["end_time"]) - datetime.fromisoformat(a["start_time"])).total_seconds()
            >= 1
            for a in waits
        )
        scopes.append(str(scope.run_id))
    assert scopes[0] != scopes[1]


def test_sigkill_worker_while_committed_provider_response_is_inflight(live_stack):
    import signal

    http = live_stack["http"]
    scope = start(http, ["S12"])
    deadline = time.monotonic() + 15
    while True:
        records = (
            http.get("http://127.0.0.1:8002/test/evidence", headers=headers("provider_reader", scope))
            .json()
            .get("records", [])
        )
        if any(r["kind"] == "fault_hit" for r in records):
            break
        assert time.monotonic() < deadline
        time.sleep(0.01)
    with live_stack["db"].connect() as c:
        process = c.execute(
            text(
                "SELECT payload FROM runtime_journal WHERE project_id=:p AND run_id=:r AND kind='lease_acquired' ORDER BY sequence DESC LIMIT 1"
            ),
            scope.params,
        ).scalar_one()["pid"]
    os.kill(process, signal.SIGKILL)
    report = wait_report(http, scope)
    save("sigkill-after-commit.json", report)
    assert report["status"] == "completed" and report["verdict"] == "pass", report["stop_reason"]
    leases = [j for j in report["runtime"]["journal"] if j["kind"] == "lease_acquired"]
    assert len(leases) == 2 and leases[1]["payload"]["epoch"] == 2
    assert report["runtime"]["recovered_event_ids"]
    ledger = http.get("http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope)).json()
    assert len(ledger["entries"]) == 1
    records = http.get(
        "http://127.0.0.1:8002/test/evidence", headers=headers("provider_reader", scope)
    ).json()["records"]
    assert len([r for r in records if r["kind"] == "execution_received"]) == 1


def test_missing_actual_fault_evidence_cannot_keep_pass(live_stack):
    from packages.transport.security import canonical, digest

    http = live_stack["http"]
    scope = start(http, ["S12"])
    assert wait_report(http, scope)["verdict"] == "pass"
    audit = uuid4()
    payload = {"purpose": "E5 required fault evidence removal counterexample"}
    with live_stack["db"].begin() as c:
        c.execute(
            text(
                "INSERT INTO reset_audits(project_id,run_id,reset_id,payload,content_hash) VALUES (:p,:r,:id,CAST(:v AS jsonb),:h)"
            ),
            scope.params | {"id": audit, "v": canonical(payload), "h": digest(payload)},
        )
        c.execute(text("SELECT set_config('simulation.reset_id',:id,true)"), {"id": str(audit)})
        c.execute(
            text(
                "DELETE FROM observations WHERE project_id=:p AND run_id=:r AND source='provider_control' AND payload->'request'->>'path'='/test/evidence'"
            ),
            scope.params,
        )
    report = http.get(
        BASE + f"/api/runs/{scope.run_id}/report", params={"project_id": str(scope.project_id)}
    ).json()
    assert report["verdict"] == "inconclusive"
    assert not report["runtime"]["faults"][0]["verified"]
    assert report["coverage"][11]["verdict"] == "inconclusive"


def test_rules_ignore_product_variant_and_test_control_payload(fixed_e5):
    from copy import deepcopy

    from packages.contracts.config import Configuration
    from packages.evaluators.refund import Policy, evaluate
    from packages.transport.security import digest

    scope, report = fixed_e5
    records = deepcopy(report["observations"])
    for o in records:
        if o["payload"].get("request", {}).get("path") == "/test/behavior":
            o["payload"]["request"]["body"]["variant"] = "buggy"
            o["digest"] = digest(o["payload"])
    result = evaluate(
        Policy.from_config(Configuration.model_validate(config_for("buggy"))), records, scope, completed=True
    )
    assert result["verdict"] == "pass" and not result["findings"]
    assert {(c["rule_id"], c["object_id"], c["verdict"]) for c in result["checks"]} == {
        (c["rule_id"], c["object_id"], c["verdict"]) for c in report["checks"]
    }


@pytest.mark.parametrize("occurred_at", [None, "2099-01-01T00:00:00+00:00"])
def test_old_callback_version_alone_cannot_override_conflicting_history(fixed_e5, occurred_at):
    from copy import deepcopy

    from packages.contracts.config import Configuration
    from packages.evaluators.refund import Policy, evaluate
    from packages.transport.security import digest

    scope, report = fixed_e5
    records = deepcopy(report["observations"])
    old = next(
        o
        for o in records
        if o["source"] == "provider_webhook" and o["payload"]["status"] == "execution_pending"
    )
    old["payload"]["occurred_at"] = occurred_at
    old["digest"] = digest(old["payload"])
    result = evaluate(
        Policy.from_config(Configuration.model_validate(config_for())), records, scope, completed=True
    )
    assert result["verdict"] != "pass" and result["observation_conflicts"]


def test_retry_budget_zero_prevents_second_provider_call(live_stack):
    scope = start(live_stack["http"], ["S15"], config_for(max_action_retries=0))
    report = wait_report(live_stack["http"], scope)
    records = (
        live_stack["http"]
        .get("http://127.0.0.1:8002/test/evidence", headers=headers("provider_reader", scope))
        .json()["records"]
    )
    assert len([r for r in records if r["kind"] == "execution_received"]) == 1
    assert report["verdict"] != "pass"
    save("retry-budget-zero.json", report)
