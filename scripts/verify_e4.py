"""Repeatable E4 acceptance with disposable DBs and actual service/PostgreSQL restarts."""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql

from packages.transport.security import Scope, headers
from scripts.demo_e4 import demonstrate

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get("ACCEPTANCE_EVIDENCE_DIR", ROOT / "docs/evidence/e4"))


def main():
    os.chdir(ROOT)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for port in [3000, 8000, 8001, 8002, 55432]:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    bundle = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(
        [str(bundle / "node/bin"), str(bundle / "bin/fallback"), env.get("PATH", "")]
    )
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    env["TEST_DATABASE_URL"] = "postgresql+psycopg://sim@127.0.0.1:55432/simulation"
    env["EVIDENCE_DIR"] = str(EVIDENCE / "browser")
    env["ACCEPTANCE_EVIDENCE_DIR"] = str(EVIDENCE)
    node = shutil.which("node", path=env["PATH"])
    pnpm = shutil.which("pnpm", path=env["PATH"])
    database = "sim_e4_acceptance_" + uuid4().hex
    env["DATABASE_URL"] = "postgresql+psycopg://sim@127.0.0.1:55432/" + database
    env["API_HOST"] = "127.0.0.1"
    env["API_PORT"] = "8000"
    env["API_BASE_URL"] = "http://127.0.0.1:8000"
    children = []
    logs = []
    created = False
    pg = None
    app = None
    result = {"at": datetime.now(timezone.utc).isoformat(), "database": "disposable real PostgreSQL"}

    def launch(name, command):
        log = (EVIDENCE / (name + ".txt")).open("a")
        logs.append(log)
        process = subprocess.Popen(
            command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        children.append(process)
        return process

    def stop(process):
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            assert process.wait(timeout=40) == 0

    def start_pg():
        process = launch("postgres", [node, "scripts/local-postgres.mjs"])
        deadline = time.monotonic() + 30
        while True:
            if process.poll() is not None:
                raise RuntimeError("PostgreSQL 启动失败")
            try:
                with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", connect_timeout=2):
                    return process
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise RuntimeError("PostgreSQL 启动超时") from None
                time.sleep(0.1)

    def start_app():
        process = launch("startup", [sys.executable, "scripts/dev.py", "--external-db"])
        deadline = time.monotonic() + 60
        with httpx.Client(trust_env=False, timeout=2) as http:
            while True:
                if process.poll() is not None:
                    raise RuntimeError("应用启动失败，见 startup.txt")
                try:
                    if (
                        http.get("http://127.0.0.1:3000").status_code == 200
                        and http.get("http://127.0.0.1:8000/api/health").status_code == 200
                    ):
                        return process
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("应用启动超时")
                time.sleep(0.2)

    def command(name, args):
        with (EVIDENCE / (name + ".txt")).open("w") as log:
            subprocess.run(args, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(name + " 通过", flush=True)

    try:
        pg = start_pg()
        command("pytest", [sys.executable, "-m", "pytest", "-q", f"--junitxml={EVIDENCE / 'pytest.xml'}"])
        with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", autocommit=True) as c:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        created = True
        app = start_app()
        command("browser", [node, "scripts/browser-smoke.mjs"])
        result["first_run"] = demonstrate()
        report = result["first_run"]["report"]
        (EVIDENCE / "report-fixed.html").write_text(result["first_run"].pop("html"))
        result["buggy_run"] = demonstrate("buggy")
        assert result["buggy_run"]["report"]["verdict"] == "fail"
        (EVIDENCE / "report-buggy.html").write_text(result["buggy_run"].pop("html"))
        (EVIDENCE / "runtime.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        env["REPORT_RUNTIME_PATH"] = str(EVIDENCE / "runtime.json")
        command("report-browser", [node, "scripts/report-browser.mjs"])
        assert report["verdict"] == "pass" and report["gate"]["verdict"] == "inconclusive"
        scope = Scope(project_id=report["project_id"], run_id=report["run_id"])
        with httpx.Client(trust_env=False, timeout=5) as http:
            first = http.get(
                "http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope)
            ).json()
        assert len(first["entries"]) == 11
        stop(app)
        app = None
        stop(pg)
        pg = None
        for port in [3000, 8000, 8001, 8002, 55432]:
            with socket.socket() as probe:
                assert probe.connect_ex(("127.0.0.1", port)) != 0
        pg = start_pg()
        app = start_app()
        with httpx.Client(trust_env=False, timeout=10) as http:
            persisted = http.get(
                f"http://127.0.0.1:8000/api/runs/{scope.run_id}/report",
                params={"project_id": str(scope.project_id)},
            ).json()
            second = http.get(
                "http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope)
            ).json()
            put = http.get(
                "http://127.0.0.1:8001/refunds/refund-S02", headers=headers("support", scope)
            ).json()
            assert second == first and put["status"] == "succeeded" and persisted["verdict"] == "pass"
            assert persisted["observations"] == report["observations"]
            assert persisted["checks"] == report["checks"]
            assert persisted["evaluation_id"] == report["evaluation_id"]
            buggy = result["buggy_run"]["report"]
            persisted_buggy = http.get(
                f"http://127.0.0.1:8000/api/runs/{buggy['run_id']}/report",
                params={"project_id": buggy["project_id"]},
            ).json()
            assert persisted_buggy["findings"] == buggy["findings"]
            assert persisted_buggy["verdict"] == "fail"
            result["restart"] = {
                "postgres_and_all_services_restarted": True,
                "same_ledger_entries": True,
                "same_observations": True,
                "same_checks_evaluation_and_findings": True,
                "put_status": put["status"],
            }
            reset = http.post(
                f"http://127.0.0.1:8000/api/runs/{scope.run_id}/reset",
                params={"project_id": str(scope.project_id)},
            )
            reset.raise_for_status()
            result["reset"] = reset.json()
        print("服务与 PostgreSQL 重启持久化、完整 reset 通过", flush=True)
        stop(app)
        app = None
        # Build generated types from a clean cache, with no development process writing it.
        generated = ROOT / "apps/web/.next"
        if generated.exists():
            shutil.rmtree(generated)
        command("build", [pnpm, "build:web"])
        command("typecheck", [pnpm, "typecheck"])
        command(
            "lint",
            [
                str(ROOT / ".venv/bin/ruff"),
                "check",
                "packages",
                "services",
                "migrations",
                "tests",
                "scripts",
                "examples",
                "adapters",
            ],
        )
        command(
            "format",
            [
                str(ROOT / ".venv/bin/ruff"),
                "format",
                "--check",
                "packages",
                "services",
                "migrations",
                "tests",
                "scripts",
                "examples",
                "adapters",
            ],
        )
        command(
            "lock-python",
            [str(ROOT / ".venv/bin/uv"), "lock", "--check", "--offline", "--cache-dir", ".local/uv-cache"],
        )
        command(
            "lock-node",
            [pnpm, "install", "--frozen-lockfile", "--offline", "--store-dir", ".local/pnpm-store"],
        )
        (EVIDENCE / "runtime.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        command("secret-scan", [sys.executable, "-m", "scripts.scan_secrets"])
        stop(app)
        app = None
        return 0
    finally:
        if app:
            stop(app)
        if created and pg and pg.poll() is None:
            with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", autocommit=True) as c:
                c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
        for child in reversed(children):
            stop(child)
        for log in logs:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
