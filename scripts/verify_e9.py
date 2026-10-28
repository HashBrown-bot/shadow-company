"""Real E9 browser acceptance on an isolated PostgreSQL database and owned services."""

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


class CICommandFailure(Exception):
    def __init__(self, stage, exit_code):
        self.stage, self.exit_code = stage, exit_code
        super().__init__(stage)


def checked_command(name, command, env, evidence):
    with (evidence / (name + ".txt")).open("w") as log:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        code = result.returncode if name == "cli-ci-gate" and result.returncode in {1, 2, 3} else 2
        raise CICommandFailure(name, code)
    print(name + " passed", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--targeted", action="store_true")
    parser.add_argument("--tests-only", action="store_true")
    parser.add_argument(
        "--serve", action="store_true", help="Keep owned review services until Ctrl-C; retain review database"
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    evidence = Path(os.environ.get("ACCEPTANCE_EVIDENCE_DIR", "docs/evidence/e9"))
    evidence.mkdir(parents=True, exist_ok=True)
    for port in [3000, 8000, 8001, 8002, 8003, 55432]:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    bundle = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(
        [str(bundle / "node/bin"), str(bundle / "bin/fallback"), env.get("PATH", "")]
    )
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    env["SIM_PG_DIRECTORY"] = str(ROOT / ".local/e9-postgres")
    env["TEST_DATABASE_URL"] = "postgresql+psycopg://sim@127.0.0.1:55432/simulation"
    env["ACCEPTANCE_EVIDENCE_DIR"] = str(evidence)
    env["EVIDENCE_DIR"] = str(evidence / "browser")
    env["API_BASE_URL"] = "http://127.0.0.1:8000"
    database = "sim_e9_acceptance_" + uuid4().hex
    env["DATABASE_URL"] = "postgresql+psycopg://sim@127.0.0.1:55432/" + database
    env["EXAMPLE_TEST_MODE"] = "1"
    registry, token_file = bootstrap(ROOT / ".local/e9-access")
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
        checked_command(name, command, env, evidence)

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
        cred = ROOT / ".local/e9-example-credentials.json"
        provision(cred)
        paths = {
            name: str(service_credentials(cred, name))
            for name in ["platform", "refund-put", "payment-provider"]
        }
        for name, port, module, extra in [
            ("api", 8000, "services.api.main:app", []),
            ("payment-provider", 8002, "main:app", ["--app-dir", "examples/payment-provider"]),
            ("refund-put", 8001, "main:app", ["--app-dir", "examples/refund-put"]),
            ("credit-note-put", 8003, "main:app", ["--app-dir", "examples/credit-note-put"]),
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
                {
                    "EXAMPLE_CREDENTIAL_FILE": paths.get(
                        "refund-put" if name == "credit-note-put" else name, paths["platform"]
                    )
                },
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
                    *(["tests/test_e9.py"] if args.targeted else []),
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
            print("E9 review ready at http://127.0.0.1:3000 (isolated PostgreSQL retained)", flush=True)
            while all(p.poll() is None for p in services.values()):
                time.sleep(1)
            raise RuntimeError("review service exited")
        command("browser", [node, "scripts/e8-browser.mjs"])
        command("access-browser", [node, "scripts/e9-access-browser.mjs"])
        command(
            "cli-ci-gate",
            [
                python,
                "-m",
                "packages.simctl",
                "run",
                "environments/refund_approval/local.e5.yaml",
                "--gate",
                "suite",
                "--output",
                str(evidence / "ci-fixed-s01-s20.json"),
            ],
        )
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
            [
                (
                    str(ROOT / ".venv/bin/uv")
                    if (ROOT / ".venv/bin/uv").exists()
                    else shutil.which("uv", path=env["PATH"])
                ),
                "lock",
                "--check",
                "--offline",
                "--cache-dir",
                ".local/uv-cache",
            ],
        )
        command(
            "lock-node",
            [
                pnpm,
                "install",
                "--frozen-lockfile",
                "--offline",
                "--store-dir",
                os.environ.get("SIM_PNPM_STORE", ".local/pnpm-store"),
            ],
        )
        command("licenses", [python, "-m", "scripts.licenses", "--output", str(evidence / "licenses.json")])
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
        return 3
    finally:
        for child in reversed(children):
            stop(child)
        # The cluster is stopped now. Acceptance DBs are dropped on a short owned restart.
        cleanup = {"owned_processes_stopped": all(p.poll() is not None for p in children)}
        if created and not args.serve:
            pg = postgres()
            with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", autocommit=True) as c:
                c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
                cleanup["temporary_database"] = database
                cleanup["temporary_database_removed"] = (
                    c.execute("SELECT count(*) FROM pg_database WHERE datname=%s", (database,)).fetchone()[0]
                    == 0
                )
                cleanup["remaining_databases"] = [
                    row[0] for row in c.execute("SELECT datname FROM pg_database ORDER BY datname").fetchall()
                ]
            stop(pg)
        for log in logs:
            log.close()
        if not args.serve:
            cleanup["ports_released"] = {}
            for port in [3000, 8000, 8001, 8002, 8003, 55432]:
                with socket.socket() as probe:
                    probe.settimeout(0.2)
                    cleanup["ports_released"][str(port)] = probe.connect_ex(("127.0.0.1", port)) != 0
            (evidence / "cleanup.json").write_text(json.dumps(cleanup, indent=2) + "\n")
            assert cleanup["owned_processes_stopped"] and all(cleanup["ports_released"].values())
            if created:
                assert cleanup["temporary_database_removed"]


def entrypoint(action=main):
    try:
        return action()
    except CICommandFailure as error:
        print(json.dumps({"stage": error.stage, "exit_code": error.exit_code, "result": "not_passed"}))
        return error.exit_code
    except KeyboardInterrupt:
        print(json.dumps({"exit_code": 3, "error": "验收已中断，运行未确认完成"}))
        return 3
    except Exception:
        print(json.dumps({"exit_code": 2, "error": "本地配置、端口或基础设施不可用；检查阶段日志"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
