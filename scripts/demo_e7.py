"""Real paired rule/hybrid local runs. No language-entry or AI-increment claim."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
import yaml

from packages.transport.access import client_headers
from scripts.demo_e6 import BASE, wait_report


def demonstrate():
    results = {}
    with httpx.Client(base_url=BASE, trust_env=False, headers=client_headers(), timeout=30) as http:
        for version in ("fixed", "buggy"):
            response = http.post("/api/projects", json={"name": "示例 E7 配对实验 " + version})
            response.raise_for_status()
            project = response.json()["id"]
            config = yaml.safe_load(Path("environments/refund_approval/local.e5.yaml").read_text())
            config["product"]["version"] = version
            response = http.put(
                f"/api/projects/{project}/contract", json={"version": version, "config": config}
            )
            response.raise_for_status()
            response = http.post(f"/api/projects/{project}/preflight", json={"contract_version": version})
            response.raise_for_status()
            assert response.json()["passed"]
            response = http.post(
                "/api/experiments",
                json={
                    "project_id": project,
                    "contract_version": version,
                    "idempotency_key": uuid4().hex,
                    "seeds": [17, 23],
                    "scenarios": ["S01", "S09", "S10", "S12"],
                    "model_budget": {"max_calls": 4, "max_tokens": 10000},
                },
            )
            response.raise_for_status()
            experiment = response.json()
            reports = []
            for item in experiment["runs"]:
                report = wait_report(http, project, item["run_id"])
                assert report["status"] == "completed"
                assert report["verdict"] == ("pass" if version == "fixed" else "fail"), report["stop_reason"]
                assert not report["actors"]["calls"] and report["budget"]["cost"]["model_calls"] == 0
                reports.append(report)
            url = "/api/experiments/" + experiment["experiment_id"]
            response = http.get(url, params={"project_id": project})
            response.raise_for_status()
            comparison = response.json()
            assert comparison["paired_conditions_verified"] and not comparison["ai_increment_proven"]
            assert all(m["review_measurement"] == "未测" for m in comparison["metrics"].values())
            page = http.get(url, params={"project_id": project, "format": "html"})
            page.raise_for_status()
            results[version] = {"experiment": comparison, "reports": reports, "html": page.text}
    return results


def main():
    results = demonstrate()
    directory = Path(".local/artifacts") / ("e7-" + results["fixed"]["experiment"]["experiment_id"])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, value in results.items():
        (directory / (name + ".html")).write_text(value.pop("html"))
    (directory / "experiments.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "artifacts": str(directory.resolve()),
                "real_model_service": "not_run",
                "ai_increment_proven": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
