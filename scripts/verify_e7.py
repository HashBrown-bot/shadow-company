"""Repeatable E7 acceptance (including E6 regressions) with disposable DBs and actual service/PostgreSQL restarts."""

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
from scripts.demo_e6 import demonstrate
from scripts.demo_e7 import demonstrate as demonstrate_e7
from scripts.protocol_e7 import demonstrate as demonstrate_protocol
from scripts.protocol_e7 import snapshot as protocol_snapshot
from services.api.database import make_engine

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get("ACCEPTANCE_EVIDENCE_DIR", ROOT / "docs/evidence/e7"))


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
    database = "sim_e7_acceptance_" + uuid4().hex
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
        command(
            "pytest",
            [sys.executable, "-m", "pytest", "-q", "--tb=short", f"--junitxml={EVIDENCE / 'pytest.xml'}"],
        )
        with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", autocommit=True) as c:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        created = True
        app = start_app()
        command("browser", [node, "scripts/browser-smoke.mjs"])
        result.update(demonstrate())
        experiments = demonstrate_e7()
        for name, value in experiments.items():
            (EVIDENCE / ("experiment-" + name + ".html")).write_text(value.pop("html"))
        (EVIDENCE / "experiments.json").write_text(json.dumps(experiments, ensure_ascii=False, indent=2))
        env["E7_RUNTIME_PATH"] = str(EVIDENCE / "experiments.json")
        command("experiment-browser", [node, "scripts/experiment-browser.mjs"])
        db = make_engine(env["DATABASE_URL"])
        protocol_scope, protocol_before = demonstrate_protocol(
            db, experiments["fixed"]["experiment"]["project_id"]
        )
        (EVIDENCE / "protocol-persistence.json").write_text(
            json.dumps(protocol_before, ensure_ascii=False, indent=2, default=str)
        )
        db.dispose()
        report = result["first_run"]["report"]
        (EVIDENCE / "report-fixed.html").write_text(result["first_run"].pop("html"))
        (EVIDENCE / "report-buggy.html").write_text(result["buggy_run"].pop("html"))
        (EVIDENCE / "compare.html").write_text(result.pop("compare_html"))
        (EVIDENCE / "runtime.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        env["REPORT_RUNTIME_PATH"] = str(EVIDENCE / "runtime.json")
        command("report-browser", [node, "scripts/report-browser.mjs"])
        command("replay-browser", [node, "scripts/replay-browser.mjs"])
        scope = Scope(project_id=report["project_id"], run_id=report["run_id"])
        source = result["buggy_run"]["report"]
        with httpx.Client(trust_env=False, timeout=20) as http:
            ledger = http.get(
                "http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope)
            ).json()
            before = http.get(
                f"http://127.0.0.1:8000/api/runs/{scope.run_id}/history",
                params={"project_id": str(scope.project_id)},
            ).json()
            original = http.get(
                f"http://127.0.0.1:8000/api/runs/{source['run_id']}/history",
                params={"project_id": source["project_id"]},
            ).json()
            assert len(ledger["entries"]) == 1 and before["replay_seals"]
            e7_histories = {}
            for value in experiments.values():
                for run in value["experiment"]["runs"]:
                    e7_histories[run["run_id"]] = http.get(
                        f"http://127.0.0.1:8000/api/runs/{run['run_id']}/history",
                        params={"project_id": value["experiment"]["project_id"]},
                    ).json()
        stop(app)
        app = None
        stop(pg)
        pg = None
        for port in [3000, 8000, 8001, 8002, 55432]:
            with socket.socket() as probe:
                assert probe.connect_ex(("127.0.0.1", port)) != 0
        pg = start_pg()
        app = start_app()
        with httpx.Client(trust_env=False, timeout=20) as http:
            after = http.get(
                f"http://127.0.0.1:8000/api/runs/{scope.run_id}/history",
                params={"project_id": str(scope.project_id)},
            ).json()
            again = http.get(
                "http://127.0.0.1:8002/test/ledger", headers=headers("provider_reader", scope)
            ).json()
            assert after == before and again == ledger
            for value in experiments.values():
                experiment = value["experiment"]
                query = {"project_id": experiment["project_id"]}
                fetched = http.get(
                    f"http://127.0.0.1:8000/api/experiments/{experiment['experiment_id']}", params=query
                )
                fetched.raise_for_status()
                assert fetched.json() == experiment
                for run in experiment["runs"]:
                    response = http.get(
                        f"http://127.0.0.1:8000/api/runs/{run['run_id']}/history", params=query
                    )
                    response.raise_for_status()
                    assert response.json() == e7_histories[run["run_id"]]
            db = make_engine(env["DATABASE_URL"])
            assert protocol_snapshot(db, protocol_scope) == protocol_before
            db.dispose()
            cleared = http.post(
                f"http://127.0.0.1:8000/api/runs/{protocol_scope.run_id}/reset",
                params={"project_id": str(protocol_scope.project_id)},
            )
            cleared.raise_for_status()
            assert cleared.json()["removed"]["actor_calls"] == 5
            assert cleared.json()["removed"]["actor_policies"] == 1
            result["e7_restart"] = {
                "same_experiments_and_metrics": True,
                "same_eight_histories_and_actor_policies": True,
                "same_protocol_calls_after_postgres_restart": True,
                "protocol_reset_removed_calls": 5,
                "model_service_test": "not_run",
                "ai_increment_proven": False,
            }
            (EVIDENCE / "e7-restart.json").write_text(
                json.dumps(result["e7_restart"], ensure_ascii=False, indent=2)
            )
            comparison = http.get(
                f"http://127.0.0.1:8000/api/runs/{source['run_id']}/compare",
                params={"project_id": source["project_id"], "other_run_id": str(scope.run_id)},
            ).json()
            assert comparison["repair_verified"]
            response = http.post(
                f"http://127.0.0.1:8000/api/runs/{scope.run_id}/reset",
                params={"project_id": str(scope.project_id)},
            )
            response.raise_for_status()
            result["reset"] = response.json()
            assert (
                result["reset"]["removed"]["replay_assets"] == 3
                and result["reset"]["removed"]["replay_seals"] == 1
            )
            assert (
                http.get(
                    f"http://127.0.0.1:8000/api/runs/{source['run_id']}/history",
                    params={"project_id": source["project_id"]},
                ).json()
                == original
            )
            result["restart"] = {
                "postgres_and_all_services_restarted": True,
                "same_history_seals_and_observations": True,
                "same_independent_ledger": True,
                "compare_still_verified": True,
                "target_reset_preserved_source": True,
            }
        print("服务/PostgreSQL 重启、不可变历史与 E6 reset 通过", flush=True)
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
