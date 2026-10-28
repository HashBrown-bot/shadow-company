"""Actual E6 replay demonstration. A helper, not the E9 simctl CLI."""

import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
import yaml

from packages.transport.access import client_headers
from packages.transport.security import digest

BASE = "http://127.0.0.1:8000"


def wait_report(http, project, run):
    deadline = time.monotonic() + 60
    while True:
        response = http.get(f"/api/runs/{run}", params={"project_id": project})
        response.raise_for_status()
        if response.json()["status"] in {"completed", "failed", "cancelled"}:
            response = http.get(f"/api/runs/{run}/report", params={"project_id": project})
            response.raise_for_status()
            return response.json()
        if time.monotonic() > deadline:
            raise RuntimeError("运行等待超时；不能声明已验证")
        time.sleep(0.1)


def demonstrate():
    with httpx.Client(base_url=BASE, trust_env=False, headers=client_headers(), timeout=20) as http:
        response = http.post("/api/projects", json={"name": "示例 E6 S12 重放与修复验证"})
        response.raise_for_status()
        project = response.json()["id"]
        preflights = {}
        for version in ("buggy", "fixed"):
            config = yaml.safe_load(Path("environments/refund_approval/local.e5.yaml").read_text())
            config["product"]["version"] = version
            response = http.put(
                f"/api/projects/{project}/contract", json={"version": version, "config": config}
            )
            response.raise_for_status()
            response = http.post(f"/api/projects/{project}/preflight", json={"contract_version": version})
            response.raise_for_status()
            preflights[version] = response.json()
            if not preflights[version]["passed"]:
                raise RuntimeError("预检未通过")
        response = http.post(
            "/api/runs",
            json={
                "project_id": project,
                "contract_version": "buggy",
                "idempotency_key": uuid4().hex,
                "suite_scope": "e6_core_20",
                "scenarios": ["S12"],
            },
        )
        response.raise_for_status()
        source = response.json()["run_id"]
        source_report = wait_report(http, project, source)
        before = http.get(f"/api/runs/{source}/history", params={"project_id": project}).json()
        response = http.post(
            f"/api/runs/{source}/replay",
            json={
                "project_id": project,
                "mode": "input",
                "target_contract_version": "fixed",
                "target_product_version": "fixed",
                "idempotency_key": uuid4().hex,
                "reuse_product_outputs": False,
            },
        )
        response.raise_for_status()
        target = response.json()["run_id"]
        target_report = wait_report(http, project, target)
        query = {"project_id": project, "other_run_id": target}
        response = http.get(f"/api/runs/{source}/compare", params=query)
        response.raise_for_status()
        comparison = response.json()
        after = http.get(f"/api/runs/{source}/history", params={"project_id": project}).json()
        assert before == after
        assert source_report["verdict"] == "fail" and target_report["verdict"] == "pass"
        assert comparison["repair_verified"] and comparison["fresh_target_calls_and_evidence"]

        def html_for(run):
            response = http.get(f"/api/runs/{run}/report", params={"project_id": project, "format": "html"})
            response.raise_for_status()
            return response.text

        result = {
            "first_run": {"report": target_report, "html": html_for(target)},
            "buggy_run": {"report": source_report, "html": html_for(source)},
            "comparison": comparison,
            "preflights": preflights,
            "history_before_hash": digest(before),
            "history_after_hash": digest(after),
        }
        result["compare_html"] = http.get(
            f"/api/runs/{source}/compare", params=query | {"format": "html"}
        ).text
        return result


def main():
    result = demonstrate()
    folder = Path(".local/artifacts") / ("e6-" + result["first_run"]["report"]["run_id"])
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for key, filename in [("first_run", "fixed"), ("buggy_run", "buggy")]:
        (folder / (filename + ".html")).write_text(result[key].pop("html"))
    (folder / "compare.html").write_text(result.pop("compare_html"))
    (folder / "runtime.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "project_id": result["comparison"]["project_id"],
                "source_run_id": result["comparison"]["source_run_id"],
                "target_run_id": result["comparison"]["target_run_id"],
                "repair_verified": result["comparison"]["repair_verified"],
                "artifacts": str(folder.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["comparison"]["repair_verified"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
