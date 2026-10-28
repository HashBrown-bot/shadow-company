"""Real E8 browser acceptance on an isolated PostgreSQL database and owned services."""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql

from packages.transport.access import bootstrap, client_headers
from packages.transport.security import provision, service_credentials

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--targeted", action="store_true")
    parser.add_argument("--tests-only", action="store_true")
    parser.add_argument(
        "--serve", action="store_true", help="Keep owned review services until Ctrl-C; retain review database"
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    evidence = Path(os.environ.get("ACCEPTANCE_EVIDENCE_DIR", "docs/evidence/e8"))
    evidence.mkdir(parents=True, exist_ok=True)
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
    env["ACCEPTANCE_EVIDENCE_DIR"] = str(evidence)
    env["EVIDENCE_DIR"] = str(evidence / "browser")
    env["API_BASE_URL"] = "http://127.0.0.1:8000"
    database = "sim_e8_acceptance_" + uuid4().hex
    env["DATABASE_URL"] = "postgresql+psycopg://sim@127.0.0.1:55432/" + database
    env["EXAMPLE_TEST_MODE"] = "1"
    registry, token_file = bootstrap(ROOT / ".local/e8-access")
    env["SIM_ACCESS_REGISTRY"] = registry
    env["SIM_TOKEN_FILE"] = token_file
    node = shutil.which("node", path=env["PATH"])
    pnpm = shutil.which("pnpm", path=env["PATH"])
    python = str(ROOT / ".venv/bin/python")
    children = []
    logs = []
    created = False
    pg = None
    services = {}
    session_path = ROOT / ".local/e8-session.json"

    def launch(name, command, extra=None):
        log = (evidence / (name + ".txt")).open("a")
        logs.append(log)
        p = subprocess.Popen(
            command, env=env | (extra or {}), stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        children.append(p)
        return p

    def stop(p):
        if p and p.poll() is None:
            os.killpg(p.pid, signal.SIGCONT)
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()

    def command(name, command):
        with (evidence / (name + ".txt")).open("w") as log:
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(name + " passed", flush=True)

    def postgres():
        p = launch("postgres", [node, "scripts/local-postgres.mjs"])
        deadline = time.monotonic() + 45
        while p.poll() is None and time.monotonic() < deadline:
            try:
                with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", connect_timeout=2):
                    return p
            except psycopg.OperationalError:
                time.sleep(0.1)
        raise RuntimeError("PostgreSQL did not become ready")

    def ready(p, url):
        deadline = time.monotonic() + 60
        with httpx.Client(trust_env=False, timeout=2) as http:
            while p.poll() is None and time.monotonic() < deadline:
                try:
                    if http.get(url).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
        raise RuntimeError("Service failed readiness: " + url)

    def start_services():
        cred = ROOT / ".local/e8-example-credentials.json"
        provision(cred)
        paths = {
            name: str(service_credentials(cred, name))
            for name in ["platform", "refund-put", "payment-provider"]
        }
        for name, port, module, extra in [
            ("api", 8000, "services.api.main:app", []),
            ("payment-provider", 8002, "main:app", ["--app-dir", "examples/payment-provider"]),
            ("refund-put", 8001, "main:app", ["--app-dir", "examples/refund-put"]),
        ]:
            services[name] = launch(
                name,
                [
                    python,
                    "-m",
                    "uvicorn",
                    module,
                    *extra,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                {"EXAMPLE_CREDENTIAL_FILE": paths.get(name, paths["platform"])},
            )
            ready(
                services[name], f"http://127.0.0.1:{port}" + ("/api/health" if name == "api" else "/health")
            )
        services["worker"] = launch(
            "worker", [python, "-m", "services.worker.main"], {"EXAMPLE_CREDENTIAL_FILE": paths["platform"]}
        )
        services["web"] = launch("web", [pnpm, "dev:web"])
        ready(services["web"], "http://127.0.0.1:3000")
        session_path.write_text(
            json.dumps(
                {"database": database, "worker_pid": services["worker"].pid, "verifier_pid": os.getpid()}
            )
        )

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        pg = postgres()
        if not args.serve:
            command(
                "pytest",
                [
                    python,
                    "-m",
                    "pytest",
                    *(["tests/test_e8_console.py"] if args.targeted else []),
                    "-q",
                    "--tb=short",
                    f"--junitxml={evidence}/pytest.xml",
                ],
            )
        if args.tests_only:
            return 0
        with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", autocommit=True) as c:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        created = True
        command("migration", [python, "-m", "alembic", "upgrade", "head"])
        start_services()
        if args.serve:
            print("E8 review ready at http://127.0.0.1:3000 (isolated PostgreSQL retained)", flush=True)
            while all(p.poll() is None for p in services.values()):
                time.sleep(1)
            raise RuntimeError("review service exited")
        command("browser", [node, "scripts/e8-browser.mjs"])
        with httpx.Client(trust_env=False, timeout=30, headers=client_headers(token_file)) as http:
            runtime = json.loads((evidence / "browser/runtime.json").read_text())
            p, r = runtime["project_id"], runtime["target_run_id"]
            before = http.get(f"http://127.0.0.1:8000/api/runs/{r}/history", params={"project_id": p}).json()
        for child in reversed(list(services.values())):
            stop(child)
        stop(pg)
        pg = postgres()
        start_services()
        with httpx.Client(trust_env=False, timeout=30, headers=client_headers(token_file)) as http:
            after = http.get(f"http://127.0.0.1:8000/api/runs/{r}/history", params={"project_id": p}).json()
            assert before == after, "history changed across real PostgreSQL restart"
        env["E8_RESTART_ONLY"] = "1"
        command("browser-restart", [node, "scripts/e8-browser.mjs"])
        for child in reversed(list(services.values())):
            stop(child)
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
        command("secret-scan", [python, "-m", "scripts.scan_secrets"])
        (evidence / "verification.json").write_text(
            json.dumps(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "result": "passed",
                    "postgres_and_all_services_restarted": True,
                    "history_unchanged": True,
                    "model_service_test": "not_run",
                },
                indent=2,
            )
            + "\n"
        )
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(children):
            stop(child)
        # The cluster is stopped now. Acceptance DBs are dropped on a short owned restart.
        if created and not args.serve:
            pg = postgres()
            with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", autocommit=True) as c:
                c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            stop(pg)
        for log in logs:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
