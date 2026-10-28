"""Repeatable E2 acceptance using real local services and a disposable browser DB."""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
import yaml
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence"


def main():
    from services.api.database import SCHEMA_REVISION

    if SCHEMA_REVISION != "0001_e2":
        print(
            "E2 验收器仅适用于 E2 原始版本；当前请运行 python -m scripts.verify_e3，历史证据保持不变。",
            file=sys.stderr,
        )
        return 2
    os.chdir(ROOT)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    bundle = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(
        [str(bundle / "node/bin"), str(bundle / "bin/fallback"), env.get("PATH", "")]
    )
    env["DATABASE_URL"] = "postgresql+psycopg://sim@127.0.0.1:55432/simulation"
    env["API_HOST"] = "127.0.0.1"
    env["API_PORT"] = "8000"
    env["API_BASE_URL"] = "http://127.0.0.1:8000"
    env["TEST_DATABASE_URL"] = env["DATABASE_URL"]
    node = shutil.which("node", path=env["PATH"])
    if not node:
        raise RuntimeError("未找到 Node")
    browser_db = "sim_browser_" + uuid4().hex
    browser_db_created = False
    child = None
    log = (EVIDENCE / "startup-e2.txt").open("w")
    client = httpx.Client(trust_env=False, timeout=3)
    results = {}

    def start():
        process = subprocess.Popen(
            [sys.executable, "scripts/dev.py"], env=env, stdout=log, stderr=subprocess.STDOUT
        )
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("一键启动失败，见 startup-e2.txt")
            try:
                health = client.get(env["API_BASE_URL"] + "/api/health")
                web = client.get("http://127.0.0.1:3000")
                if health.status_code == 200 and web.status_code == 200:
                    return process
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        process.terminate()
        process.wait(timeout=30)
        raise RuntimeError("启动超时")

    def stop(process):
        process.terminate()
        assert process.wait(timeout=35) == 0
        for port in [3000, 8000, 8001, 8002, 55432]:
            with socket.socket() as probe:
                assert probe.connect_ex(("127.0.0.1", port)) != 0, f"停止后端口 {port} 仍被占用"

    try:
        child = start()
        for name, url in [
            ("api", "http://127.0.0.1:8000/api/health"),
            ("refund-put", "http://127.0.0.1:8001/health"),
            ("payment-provider", "http://127.0.0.1:8002/health"),
        ]:
            response = client.get(url)
            response.raise_for_status()
            results[name] = response.json()
        with (EVIDENCE / "pytest-e2.txt").open("w") as output:
            subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--junitxml=docs/evidence/pytest-e2.xml"],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
            )
        print("后端测试通过", flush=True)
        worker = subprocess.run(
            [sys.executable, "-m", "services.worker.main", "--check"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        results["worker"] = json.loads(worker.stdout)
        config = yaml.safe_load(Path("environments/refund_approval/example.v0.2.yaml").read_text())
        results["negative_contracts"] = {}
        for name in ["missing_provider_ledger", "negative_budget", "unsupported_mode"]:
            changed = deepcopy(config)
            if name == "missing_provider_ledger":
                del changed["product"]["observations"]["provider_ledger"]
            elif name == "negative_budget":
                changed["runtime"]["max_events"] = -1
            else:
                changed["runtime"]["time_mode"] = "controlled"
            response = client.post(
                env["API_BASE_URL"] + "/api/contracts/validate", json={"yaml": yaml.safe_dump(changed)}
            )
            assert response.status_code == 422
            results["negative_contracts"][name] = {
                "http_status": 422,
                "details": response.json()["error"]["details"],
            }
        conflict = subprocess.run([sys.executable, "scripts/dev.py"], env=env, capture_output=True, text=True)
        assert conflict.returncode == 2 and "已被占用" in conflict.stderr
        assert client.get(env["API_BASE_URL"] + "/api/health").status_code == 200
        results["port_conflict"] = "rejected_before_start; existing services remain healthy"
        ids = [p["id"] for p in client.get(env["API_BASE_URL"] + "/api/projects").json()["items"]]
        stop(child)
        child = None
        child = start()
        after = [p["id"] for p in client.get(env["API_BASE_URL"] + "/api/projects").json()["items"]]
        assert ids == after
        results["restart"] = {
            "same_project_ids": True,
            "project_count": len(ids),
            "all_ports_released_on_stop": True,
        }
        print("停止、重启及持久化验证通过", flush=True)
        with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(browser_db)))
        browser_db_created = True
        stop(child)
        child = None
        env["DATABASE_URL"] = "postgresql+psycopg://sim@127.0.0.1:55432/" + browser_db
        child = start()
        with (EVIDENCE / "browser-e2.txt").open("w") as output:
            subprocess.run(
                [node, "scripts/browser-smoke.mjs"],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
            )
        print("独立空库浏览器验收通过", flush=True)
        results["browser_database"] = "disposable database; never cleared development data"
        with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(browser_db)))
        browser_db_created = False
        stop(child)
        child = None
        (EVIDENCE / "runtime-e2.json").write_text(
            json.dumps(
                {"at": datetime.now(timezone.utc).isoformat(), "checks": results},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        return 0
    finally:
        if browser_db_created:
            try:
                with psycopg.connect("postgresql://sim@127.0.0.1:55432/postgres", autocommit=True) as conn:
                    conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(browser_db)))
            except psycopg.Error:
                print(f"临时验收库 {browser_db} 未自动删除，请在数据库可用后清理", file=sys.stderr)
        if child and child.poll() is None:
            stop(child)
        client.close()
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
