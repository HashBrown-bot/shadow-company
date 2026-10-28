"""Demonstrate actual local E3 calls; no model and no credentials in output."""

import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
import yaml

from packages.transport.access import client_headers


def demonstrate():
    with httpx.Client(
        base_url="http://127.0.0.1:8000", trust_env=False, headers=client_headers(), timeout=20
    ) as http:
        response = http.post("/api/projects", json={"name": "示例 E3 退款闭环"})
        response.raise_for_status()
        project_id = response.json()["id"]
        config = yaml.safe_load(Path("environments/refund_approval/local.e3.yaml").read_text())
        response = http.put(
            f"/api/projects/{project_id}/contract", json={"version": "e3-v1", "config": config}
        )
        response.raise_for_status()
        response = http.post(f"/api/projects/{project_id}/preflight", json={"contract_version": "e3-v1"})
        response.raise_for_status()
        preflight = response.json()
        if not preflight["passed"]:
            raise RuntimeError("预检未通过；不启动业务运行")
        response = http.post(
            "/api/runs",
            json={
                "project_id": project_id,
                "contract_version": "e3-v1",
                "idempotency_key": uuid4().hex,
                "scenarios": ["S01", "S02"],
            },
        )
        response.raise_for_status()
        run_id = response.json()["run_id"]
        deadline = time.monotonic() + 40
        while True:
            response = http.get(f"/api/runs/{run_id}/report", params={"project_id": project_id})
            response.raise_for_status()
            report = response.json()
            if report["status"] in {"completed", "failed", "cancelled"}:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("等待 Worker 超时，不能宣称通过")
            time.sleep(0.1)
        return {"preflight": preflight, "report": report}


def main():
    result = demonstrate()
    report = result["report"]
    target = Path(".local/artifacts") / f"e3-{report['run_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    target.chmod(0o600)
    print(
        json.dumps(
            {
                "project_id": report["project_id"],
                "run_id": report["run_id"],
                "e3_flow": report["e3_flow"],
                "full_suite_gate": report["gate"]["verdict"],
                "report": str(target),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["e3_flow"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
