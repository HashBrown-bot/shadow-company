"""Start only this project's loopback services; Ctrl-C stops child processes."""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wait_health(url, process, timeout=45):
    # Loopback readiness must bypass OS proxy settings (common on macOS).
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("服务提前退出，请查看 .local/logs")
        try:
            with opener.open(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    raise RuntimeError("服务启动超时，请查看 .local/logs")


def main():
    parser = argparse.ArgumentParser(description="启动 E9 本地服务；Ctrl-C 安全停止，保留本地数据库")
    parser.add_argument(
        "--external-db", action="store_true", help="使用已启动的 DATABASE_URL，不再启动本地 PostgreSQL"
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    env = os.environ.copy()
    if Path(".env").exists():
        for line in Path(".env").read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip().strip("\"'"))
    bundle = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
    env["PATH"] = os.pathsep.join(
        [str(ROOT / ".venv/bin"), str(bundle / "node/bin"), str(bundle / "bin/fallback"), env.get("PATH", "")]
    )
    from packages.transport.access import bootstrap

    registry, token_file = bootstrap(ROOT / ".local/access")
    env["SIM_ACCESS_REGISTRY"] = registry
    env["SIM_TOKEN_FILE"] = token_file
    from packages.transport.security import provision, service_credentials

    credentials = ROOT / ".local/example-credentials.json"
    provision(credentials)
    credential_paths = {
        name: str(service_credentials(credentials, name))
        for name in ("refund-put", "payment-provider", "platform")
    }
    env["EXAMPLE_CREDENTIAL_FILE"] = credential_paths["platform"]
    env["EXAMPLE_TEST_MODE"] = "1"
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    if env.get("API_HOST", "127.0.0.1") not in {"127.0.0.1", "::1", "localhost"}:
        raise RuntimeError("本地启动器仅允许 loopback API_HOST")
    host = env.get("API_HOST", "127.0.0.1")
    port = str(int(env.get("API_PORT", "8000")))
    origin_host = f"[{host}]" if ":" in host else host
    env.setdefault("API_BASE_URL", f"http://{origin_host}:{port}")
    if port != "8000" or host != "127.0.0.1":
        raise RuntimeError("E3 示例回调仅批准 127.0.0.1:8000；其他 origin 需要单独接入审阅")
    node, pnpm = (shutil.which(name, path=env["PATH"]) for name in ("node", "pnpm"))
    python = ROOT / ".venv/bin/python"
    if not node or not pnpm or not python.exists():
        raise RuntimeError("请先按 README 安装 Python、Node、pnpm 与项目依赖")
    # Do not mistake another process's HTTP 200 for this startup's readiness.
    ports = [int(port), 8001, 8002, 8003, 3000] + ([] if args.external_db else [55432])
    if len(set(ports)) != len(ports):
        raise RuntimeError("API_PORT 与其他本地服务端口冲突")
    for local_port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            # Closed connections in TIME_WAIT are reusable and are not listeners.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", local_port))
            except OSError:
                raise RuntimeError(f"本地端口 {local_port} 已被占用；请先停止已确认的旧服务") from None
    log_dir = ROOT / ".local/logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    children, logs = [], []

    def start(name, command):
        log = (log_dir / f"{name}.log").open("a")
        logs.append(log)
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env
            | {
                "EXAMPLE_CREDENTIAL_FILE": credential_paths.get(
                    "refund-put" if name == "credit-note-put" else name, credential_paths["platform"]
                )
            },
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        children.append(child)
        print(f"启动 {name}（日志 .local/logs/{name}.log）", flush=True)
        return child

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        if not args.external_db:
            pg = start("postgres", [node, "scripts/local-postgres.mjs"])
            import psycopg

            deadline = time.monotonic() + 45
            while True:
                if pg.poll() is not None:
                    raise RuntimeError("PostgreSQL 提前退出，请查看本地日志")
                try:
                    with psycopg.connect("postgresql://sim@127.0.0.1:55432/simulation", connect_timeout=2):
                        break
                except psycopg.OperationalError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("PostgreSQL 启动超时") from None
                    time.sleep(0.2)
        subprocess.run([str(python), "-m", "alembic", "upgrade", "head"], env=env, check=True)
        api = start(
            "api", [str(python), "-m", "uvicorn", "services.api.main:app", "--host", host, "--port", port]
        )
        wait_health(env["API_BASE_URL"] + "/api/health", api)
        start("worker", [str(python), "-m", "services.worker.main"])
        for name, sample_port in [
            ("refund-put", "8001"),
            ("payment-provider", "8002"),
            ("credit-note-put", "8003"),
        ]:
            sample = start(
                name,
                [
                    str(python),
                    "-m",
                    "uvicorn",
                    "main:app",
                    "--app-dir",
                    f"examples/{name}",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    sample_port,
                ],
            )
            wait_health(f"http://127.0.0.1:{sample_port}/health", sample)
        web = start("web", [pnpm, "dev:web"])
        wait_health("http://127.0.0.1:3000", web)
        print(
            json.dumps(
                {
                    "web": "http://127.0.0.1:3000",
                    "api": env["API_BASE_URL"] + "/api/docs",
                    "phase": "E9",
                    "business_execution": "e5_s01_s20",
                }
            ),
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError("有子服务退出，请检查 .local/logs")
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
