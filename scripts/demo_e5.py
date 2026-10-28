"""Run actual E5 examples and export source-backed JSON and HTML reports."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
import yaml

from packages.simulator.e5 import SCENARIOS
from packages.transport.access import client_headers


def demonstrate(version="fixed"):
    with httpx.Client(
        base_url="http://127.0.0.1:8000", trust_env=False, headers=client_headers(), timeout=20
    ) as http:
        response = http.post("/api/projects", json={"name": "示例 E5 规则评估 " + version})
        response.raise_for_status()
        project = response.json()["id"]
        config = yaml.safe_load(Path("environments/refund_approval/local.e5.yaml").read_text())
        config["product"]["version"] = version
        response = http.put(f"/api/projects/{project}/contract", json={"version": "e5-v1", "config": config})
        response.raise_for_status()
        response = http.post(f"/api/projects/{project}/preflight", json={"contract_version": "e5-v1"})
        response.raise_for_status()
        preflight = response.json()
        if not preflight["passed"]:
            raise RuntimeError("预检失败；不执行业务")
        response = http.post(
            "/api/runs",
            json={
                "project_id": project,
                "contract_version": "e5-v1",
                "idempotency_key": uuid4().hex,
                "suite_scope": "e5_core_20",
                "scenarios": list(SCENARIOS),
            },
        )
        response.raise_for_status()
        run_id = response.json()["run_id"]
        deadline = time.monotonic() + 45
        while True:
            response = http.get(f"/api/runs/{run_id}", params={"project_id": project})
            response.raise_for_status()
            if response.json()["status"] in {"completed", "failed", "cancelled"}:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("等待 Worker 超时，验证未完成")
            time.sleep(0.1)
        response = http.get(f"/api/runs/{run_id}/report", params={"project_id": project})
        response.raise_for_status()
        report = response.json()
        response = http.get(f"/api/runs/{run_id}/report", params={"project_id": project, "format": "html"})
        response.raise_for_status()
        return {"preflight": preflight, "report": report, "html": response.text}


def main():
    parser = argparse.ArgumentParser(description="本机 E5 示例助手；不是 E9 simctl")
    parser.add_argument("--version", choices=["fixed", "buggy"], default="fixed")
    args = parser.parse_args()
    result = demonstrate(args.version)
    report = result["report"]
    directory = Path(".local/artifacts")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    paths = []
    for extension, value in [
        ("json", json.dumps({k: v for k, v in result.items() if k != "html"}, ensure_ascii=False, indent=2)),
        ("html", result["html"]),
    ]:
        path = directory / f"e5-{report['run_id']}.{extension}"
        path.write_text(value)
        path.chmod(0o600)
        paths.append(str(path.resolve()))
    print(
        json.dumps(
            {
                "project_id": report["project_id"],
                "run_id": report["run_id"],
                "selected_verdict": report["verdict"],
                "full_suite_gate": report["gate"]["verdict"],
                "reports": paths,
            },
            ensure_ascii=False,
        )
    )
    return {"pass": 0, "fail": 1, "inconclusive": 3}.get(report["verdict"], 3)


if __name__ == "__main__":
    raise SystemExit(main())
