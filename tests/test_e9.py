"""E9 actual CLI/HTTP/PostgreSQL boundaries. No external services or model credentials."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from packages.evaluators.gates import gate_result
from packages.transport.access import client_headers, issue, private_read, write_private
from packages.transport.security import Scope, canonical, digest
from services.api.main import create_app
from tests.test_e4_live import BASE
from tests.test_e5_live import config_for, save, wait_report


def cli(*args, expected=None):
    result = subprocess.run(
        [sys.executable, "-m", "packages.simctl", *map(str, args)], capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    assert not result.stderr, result.stderr
    assert data["exit_code"] == result.returncode
    if expected is not None:
        assert result.returncode == expected, data
    return result.returncode, data


def config_path(tmp_path, version="fixed", credit=False, **runtime):
    config = (
        yaml.safe_load(Path("environments/refund_approval/local.e9-credit.yaml").read_text())
        if credit
        else config_for(version, **runtime)
    )
    config["product"]["version"] = version
    config["runtime"].update(runtime)
    path = tmp_path / (str(uuid4()) + ".yaml")
    path.write_text(yaml.safe_dump(config))
    return path


def grant_file(tmp_path, projects, permissions, runs=None):
    path = tmp_path / (uuid4().hex + ".token")
    issued = issue(
        os.environ["SIM_ACCESS_REGISTRY"], path, projects=projects, permissions=permissions, runs=runs
    )
    return path, issued


def test_cli_help_validation_and_redacted_errors(tmp_path):
    for name in [None, "validate", "preflight", "run", "report", "replay", "compare"]:
        args = [sys.executable, "-m", "packages.simctl"] + ([name] if name else []) + ["--help"]
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode == 0 and "usage:" in result.stdout
    _, result = cli("validate", "environments/refund_approval/local.e5.yaml", "--json", expected=0)
    assert result["data"]["business_verdict"] == "inconclusive"
    canary = "secret-canary-" + uuid4().hex
    path = tmp_path / "invalid.yaml"
    path.write_text("unexpected: " + canary)
    _, result = cli("validate", path, expected=2)
    assert canary not in json.dumps(result)
    _, result = cli("run", "--unknown-argument", canary, expected=2)
    assert canary not in json.dumps(result)


@pytest.fixture(scope="module")
def cli_pair(live_stack, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e9-cli")
    _, buggy = cli("run", config_path(tmp, "buggy"), "--scenarios", "S01,S02,S04,S12", expected=1)
    report = buggy["data"]
    p, source = report["project_id"], report["run_id"]
    _, pf = cli("preflight", config_path(tmp), "--project", p, "--contract-version", "e9-fixed", expected=0)
    assert pf["data"]["preflight"]["passed"]
    _, fixed = cli(
        "replay",
        "--project",
        p,
        "--source",
        source,
        "--target-contract",
        "e9-fixed",
        "--target-version",
        "fixed",
        expected=0,
    )
    target = fixed["data"]["run_id"]
    _, compared = cli("compare", "--project", p, "--source", source, "--target", target, expected=0)
    assert compared["data"]["comparison"]["repair_verified"]
    save("e9-cli-buggy.json", buggy)
    save("e9-cli-fixed.json", fixed)
    save("e9-cli-compare.json", compared)
    return p, source, target, fixed["data"]


def test_cli_real_exit_codes_replay_and_export(cli_pair, live_stack, tmp_path):
    p, source, target, report = cli_pair
    ci_results = []

    def through_ci(expected, *args):
        # Exercise the exact CI subprocess and outer-exit bridge against real API results.
        directory = tmp_path / f"ci-{expected}"
        directory.mkdir()
        driver = """import os,sys
from pathlib import Path
from scripts.verify_e9 import checked_command,entrypoint
raise SystemExit(entrypoint(lambda: checked_command('cli-ci-gate',
    [sys.executable,'-m','packages.simctl',*sys.argv[2:]],os.environ.copy(),Path(sys.argv[1])) or 0))
"""
        result = subprocess.run(
            [sys.executable, "-c", driver, str(directory), *args], capture_output=True, text=True
        )
        output = json.loads((directory / "cli-ci-gate.txt").read_text())
        assert result.returncode == output["exit_code"] == expected
        assert not result.stderr
        ci_results.append({"cli_exit_code": output["exit_code"], "ci_exit_code": result.returncode})

    through_ci(0, "report", "--project", p, "--run", target)
    through_ci(1, "report", "--project", p, "--run", source)
    through_ci(3, "report", "--project", p, "--run", target, "--gate", "suite")
    _, history = cli("replay", "--project", p, "--source", source, "--mode", "history", expected=0)
    assert history["data"]["business_gate"] == "not_evaluated"
    path = tmp_path / "report.html"
    cli("report", "--project", p, "--run", target, "--format", "html", "--output", path, expected=0)
    assert "[REDACTED]" in path.read_text()
    cli("report", "--project", p, "--run", target, "--output", path, expected=2)
    cli("report", "--project", p, "--run", target, "--gate", "suite", expected=3)
    _, budget = cli("run", config_path(tmp_path, max_events=1), "--scenarios", "S01,S02", expected=3)
    assert budget["data"]["stop_reason"] == "budget_exhausted"
    save("e9-cli-budget.json", budget)
    _, narrow = cli("run", config_path(tmp_path), "--scenarios", "S01", expected=3)
    assert narrow["data"]["verdict"] == "pass"
    assert any("APPROVAL_001" in reason for reason in narrow["data"]["ci_gates"]["selected"]["reasons"])
    # A real missing fixture fails even if a caller tampers with a cached verdict field.
    changed = json.loads(json.dumps(report))
    for check in changed["checks"]:
        if check["rule_id"] == "REFUND_001":
            check["verdict"] = "not_applicable"
    assert gate_result(changed)["exit_code"] == 3
    provider = live_stack["children"][1]
    os.kill(provider.pid, signal.SIGSTOP)
    try:
        _, unavailable = cli("preflight", "--project", p, "--contract-version", "e9-fixed", expected=2)
        assert unavailable["data"]["preflight"]["passed"] is False
        save("e9-cli-infrastructure.json", unavailable)
        through_ci(2, "preflight", "--project", p, "--contract-version", "e9-fixed")
    finally:
        os.kill(provider.pid, signal.SIGCONT)
    save("e9-ci-exit-codes.json", {"actual_subprocess_results": ci_results})


def test_project_run_permissions_expiry_revocation_and_private_evidence(cli_pair, live_stack, tmp_path):
    p, source, target, report = cli_pair
    http = live_stack["http"]
    other = http.post(BASE + "/api/projects", json={"name": "isolated peer"}).json()["id"]
    path, issued = grant_file(tmp_path, [p], ["read"])
    with httpx.Client(trust_env=False, headers=client_headers(path)) as viewer:
        assert viewer.get(BASE + "/api/projects").json()["total"] == 1
        assert viewer.get(BASE + f"/api/projects/{other}").status_code == 403
        assert viewer.get(BASE + f"/api/runs/{target}/report", params={"project_id": p}).status_code == 403
        assert viewer.get(BASE + f"/api/runs/{target}/checks", params={"project_id": p}).status_code == 403
        assert viewer.post(BASE + f"/api/runs/{target}/cancel", params={"project_id": p}).status_code == 403
    run_file, _ = grant_file(tmp_path, [p], ["read", "evidence"], [target])
    with httpx.Client(trust_env=False, headers=client_headers(run_file)) as limited:
        assert limited.get(BASE + f"/api/runs/{target}", params={"project_id": p}).status_code == 200
        assert limited.get(BASE + f"/api/runs/{target}/checks", params={"project_id": p}).status_code == 200
        assert limited.get(BASE + f"/api/runs/{source}", params={"project_id": p}).status_code == 403
        assert (
            limited.get(
                BASE + f"/api/runs/{target}/compare", params={"project_id": p, "other_run_id": source}
            ).status_code
            == 403
        )
        assert limited.get(BASE + f"/api/projects/{p}/runs").status_code == 403
        raw = f"/api/runs/{target}/raw-evidence/" + report["observations"][0]["observation_id"]
        assert limited.get(BASE + raw, params={"project_id": p}).status_code == 403
    assert http.get(BASE + raw, params={"project_id": p}).status_code == 200
    assert http.get(BASE + raw, params={"project_id": other}).status_code == 404
    assert http.get(BASE + "/api/projects", headers={"Authorization": ""}).status_code == 401
    registry = os.environ["SIM_ACCESS_REGISTRY"]
    grants = json.loads(private_read(registry))
    next(g for g in grants["grants"] if g["id"] == issued["id"])["expires_at"] = 0
    write_private(registry, json.dumps(grants))
    assert http.get(BASE + "/api/projects", headers=client_headers(path)).status_code == 401
    next(g for g in grants["grants"] if g["id"] == issued["id"]).update(expires_at=9999999999, revoked=True)
    write_private(registry, json.dumps(grants))
    assert http.get(BASE + "/api/projects", headers=client_headers(path)).status_code == 401
    save(
        "e9-access.json",
        {
            "project_id": p,
            "run_id": target,
            "peer_project_id": other,
            "read_only_denied_evidence": True,
            "run_scope_denied_peer": True,
            "expired_and_revoked_denied": True,
        },
    )


def test_second_rpc_adapter_real_buggy_fixed_and_isolation(live_stack, tmp_path):
    values = []
    for variant, expected in [("buggy", 1), ("fixed", 0)]:
        _, result = cli(
            "run",
            config_path(tmp_path, variant, credit=True),
            "--suite-scope",
            "e4_core_10",
            "--scenarios",
            ",".join(f"S{i:02}" for i in range(1, 11)),
            expected=expected,
        )
        report = result["data"]
        assert report["versions"]["adapter"] == "rpc_credit_v1"
        assert len([c for c in report["coverage"] if c["status"] == "executed"]) == 10
        wire = [
            o["payload"]["response"]["wire"]
            for o in report["observations"]
            if "wire" in o["payload"].get("response", {})
        ]
        assert wire and all(w["method"] == "POST" and w["path"] == "/rpc" for w in wire)
        assert any(w["request"]["method"] == "notes.settle" for w in wire)
        issued = [w["request"]["params"] for w in wire if w["request"]["method"] == "notes.issue"]
        assert issued and all(row["payee"].startswith("sha256:") for row in issued)
        if variant == "buggy":
            assert any(c["rule_id"] == "APPROVAL_001" and c["verdict"] == "fail" for c in report["checks"])
        save("e9-second-" + variant + ".json", result)
        values.append(report)
    with live_stack["db"].connect() as c:
        for r in values:
            params = {"p": r["project_id"], "r": r["run_id"]}
            assert (
                c.execute(
                    text("SELECT count(*) FROM credit_note.notes WHERE project_id=:p AND run_id=:r"), params
                ).scalar_one()
                > 0
            )
            assert (
                c.execute(
                    text("SELECT count(*) FROM refund_put.refunds WHERE project_id=:p AND run_id=:r"), params
                ).scalar_one()
                == 0
            )
    a = {
        e
        for r in values[:1]
        for o in r["observations"]
        if o["source"] == "provider_ledger"
        for e in [x["entry_id"] for x in o["payload"]["response"]["body"]["entries"]]
    }
    b = {
        e
        for r in values[1:]
        for o in r["observations"]
        if o["source"] == "provider_ledger"
        for e in [x["entry_id"] for x in o["payload"]["response"]["body"]["entries"]]
    }
    assert a and b and not a & b


def test_retention_delete_provenance_and_emergency_stop(live_stack, tmp_path):
    _, data = cli("run", config_path(tmp_path), "--scenarios", "S01,S02", expected=0)
    report = data["data"]
    p, r = report["project_id"], report["run_id"]
    http, db = live_stack["http"], live_stack["db"]
    # Expiry is tested using the actual stored policy: create a zero-day private-evidence contract.
    conf = config_for()
    conf["artifacts"].update(raw_retention_days=0, trace_retention_days=0)
    http.put(
        BASE + f"/api/projects/{p}/contract", json={"version": "expire", "config": conf}
    ).raise_for_status()
    assert http.post(BASE + f"/api/projects/{p}/preflight", json={"contract_version": "expire"}).json()[
        "passed"
    ]
    submitted = http.post(
        BASE + "/api/runs",
        json={
            "project_id": p,
            "contract_version": "expire",
            "idempotency_key": uuid4().hex,
            "suite_scope": "e6_core_20",
            "scenarios": ["S01", "S02"],
        },
    ).json()
    expired = wait_report(http, Scope(project_id=p, run_id=submitted["run_id"]))
    raw = f"/api/runs/{expired['run_id']}/raw-evidence/" + expired["observations"][0]["observation_id"]
    assert http.get(BASE + raw, params={"project_id": p}).status_code == 404
    retained = http.post(BASE + f"/api/projects/{p}/retention").json()
    assert retained["raw_removed"] > 0 and retained["trace_runs_reset"] > 0
    response = http.post(BASE + f"/api/projects/{p}/emergency-stop")
    assert response.status_code == 200 and response.json()["stopped"]
    blocked = http.post(
        BASE + "/api/runs",
        json={
            "project_id": p,
            "contract_version": report["versions"]["contract"],
            "idempotency_key": uuid4().hex,
            "suite_scope": "e6_core_20",
            "scenarios": ["S01"],
        },
    )
    assert blocked.status_code == 409
    assert http.post(BASE + f"/api/projects/{p}/resume").json()["resumed"]
    removed = http.delete(BASE + f"/api/projects/{p}")
    assert removed.status_code == 200, removed.text
    assert http.get(BASE + f"/api/runs/{r}", params={"project_id": p}).status_code == 404
    with db.connect() as c:
        for table in [
            "contracts",
            "runs",
            "observations",
            "private_evidence",
            "refund_put.namespaces",
            "payment_provider.namespaces",
            "preflights",
            "reset_audits",
        ]:
            assert (
                c.execute(text(f"SELECT count(*) FROM {table} WHERE project_id=:p"), {"p": p}).scalar_one()
                == 0
            )
        audits = [
            dict(row)
            for row in c.execute(
                text("SELECT * FROM lifecycle_audits WHERE project_id=:p"), {"p": p}
            ).mappings()
        ]
    assert audits and any(a["operation"] == "delete_project" for a in audits)
    assert all(
        set(a) == {"audit_id", "project_id", "run_id", "operation", "created_at", "record_count"}
        for a in audits
    )
    save(
        "e9-lifecycle.json",
        {"project_id": p, "run_id": r, "retention": retained, "deletion": removed.json(), "audits": audits},
    )
    with pytest.raises(IntegrityError):
        with db.begin() as c:
            c.execute(text("DELETE FROM lifecycle_audits WHERE project_id=:p"), {"p": p})


def test_missing_access_configuration_fails_closed(database, monkeypatch):
    monkeypatch.setenv("SIM_ACCESS_REGISTRY", "/nonexistent/e9-grants.json")
    with TestClient(create_app(database)) as anonymous:
        assert anonymous.get("/api/projects").status_code == 401
        assert (
            anonymous.get("/api/projects", headers={"Authorization": "Bearer sim_" + "x" * 43}).status_code
            == 503
        )


def test_evidence_loss_cli_blocks_and_project_stop_cancels_real_jobs(live_stack, tmp_path):
    _, data = cli("run", config_path(tmp_path), "--scenarios", "S01,S02", expected=0)
    report = data["data"]
    p, r = report["project_id"], report["run_id"]
    http, db = live_stack["http"], live_stack["db"]
    with db.begin() as c:
        audit = uuid4()
        payload = {"purpose": "E9 required evidence loss negative test"}
        c.execute(
            text(
                "INSERT INTO reset_audits(project_id,run_id,reset_id,payload,content_hash) VALUES (:p,:r,:a,CAST(:v AS jsonb),:h)"
            ),
            {"p": p, "r": r, "a": audit, "v": canonical(payload), "h": digest(payload)},
        )
        c.execute(text("SELECT set_config('simulation.reset_id',:id,true)"), {"id": str(audit)})
        assert c.execute(
            text("DELETE FROM observations WHERE project_id=:p AND run_id=:r AND source='provider_ledger'"),
            {"p": p, "r": r},
        ).rowcount
    _, lost = cli("report", "--project", p, "--run", r, expected=3)
    save("e9-cli-evidence-loss.json", lost)
    version = report["versions"]["contract"]
    submitted = http.post(
        BASE + "/api/runs",
        json={
            "project_id": p,
            "contract_version": version,
            "idempotency_key": uuid4().hex,
            "suite_scope": "e6_core_20",
            "scenarios": ["S18"],
        },
    ).json()
    scope = Scope(project_id=p, run_id=submitted["run_id"])
    deadline = time.monotonic() + 15
    while True:
        with db.connect() as c:
            if c.execute(
                text(
                    "SELECT 1 FROM runtime_journal WHERE project_id=:p AND run_id=:r AND kind='dispatch_started' LIMIT 1"
                ),
                scope.params,
            ).scalar():
                break
        assert time.monotonic() < deadline
        time.sleep(0.02)
    queued = http.post(
        BASE + "/api/runs",
        json={
            "project_id": p,
            "contract_version": version,
            "idempotency_key": uuid4().hex,
            "suite_scope": "e6_core_20",
            "scenarios": ["S01"],
        },
    ).json()
    stopped = http.post(BASE + f"/api/projects/{p}/emergency-stop")
    assert stopped.status_code == 200 and stopped.json()["cancel_requested"] == 2
    for rid in (str(scope.run_id), queued["run_id"]):
        ended = wait_report(http, Scope(project_id=p, run_id=rid))
        assert ended["status"] == "cancelled"
        cli("report", "--project", p, "--run", rid, expected=3)
    with db.connect() as c:
        assert not c.execute(
            text(
                "SELECT 1 FROM runtime_journal WHERE project_id=:p AND run_id=:r AND kind='dispatch_started' LIMIT 1"
            ),
            {"p": p, "r": queued["run_id"]},
        ).scalar()
    save(
        "e9-emergency-stop.json",
        {
            "project_id": p,
            "active_run_id": str(scope.run_id),
            "queued_run_id": queued["run_id"],
            "result": stopped.json(),
            "both_cancelled": True,
        },
    )


def test_delete_failure_keeps_evidence_and_cannot_authorize_other_project(live_stack, tmp_path):
    _, data = cli("run", config_path(tmp_path), "--scenarios", "S01,S02", expected=0)
    report = data["data"]
    p, r = report["project_id"], report["run_id"]
    http, db = live_stack["http"], live_stack["db"]
    reader, _ = grant_file(tmp_path, [p], ["read", "evidence"])
    assert (
        http.post(
            BASE + "/api/experiments", headers=client_headers(reader), json={"project_id": p}
        ).status_code
        == 403
    )
    provider = live_stack["children"][1]
    os.kill(provider.pid, signal.SIGSTOP)
    try:
        response = http.delete(BASE + f"/api/projects/{p}", timeout=20)
        assert response.status_code == 503
        with db.connect() as c:
            assert (
                c.execute(
                    text("SELECT count(*) FROM observations WHERE project_id=:p AND run_id=:r"),
                    {"p": p, "r": r},
                ).scalar_one()
                > 0
            )
    finally:
        os.kill(provider.pid, signal.SIGCONT)
    assert http.delete(BASE + f"/api/projects/{p}", timeout=20).status_code == 200
