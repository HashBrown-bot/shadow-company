"""Authorized local demo through simctl: creates its own project, never resets existing runs."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from packages.simctl.main import Client, config_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    client = Client(
        SimpleNamespace(
            api_url="http://127.0.0.1:8000",
            token_file=os.environ.get("SIM_TOKEN_FILE", ".local/access/operator.token"),
        )
    )
    project = client.request("POST", "projects", {"name": "示例 · E9 CLI buggy/fixed 演示"})["id"]
    for version in ("buggy", "fixed"):
        config = config_file("environments/refund_approval/local.e5.yaml").model_dump(mode="json")
        config["product"]["version"] = version
        client.request("PUT", f"projects/{project}/contract", {"version": version, "config": config})

    def run(name, expected, *command):
        result = subprocess.run(
            [sys.executable, "-m", "packages.simctl", *command], capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        (directory / (name + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        if result.returncode != expected:
            raise RuntimeError(
                f"{name}: expected exit {expected}, got {result.returncode}; inspect saved JSON"
            )
        return data["data"]

    buggy = run(
        "buggy",
        1,
        "run",
        "--project",
        project,
        "--contract-version",
        "buggy",
        "--scenarios",
        "S01,S02,S04,S12",
    )
    fixed = run(
        "fixed",
        0,
        "replay",
        "--project",
        project,
        "--source",
        buggy["run_id"],
        "--target-contract",
        "fixed",
        "--target-version",
        "fixed",
    )
    compared = run(
        "compare",
        0,
        "compare",
        "--project",
        project,
        "--source",
        buggy["run_id"],
        "--target",
        fixed["run_id"],
    )
    assert compared["comparison"]["repair_verified"]
    summary = {
        "example": True,
        "project_id": project,
        "buggy_run_id": buggy["run_id"],
        "fixed_run_id": fixed["run_id"],
        "exit_codes": [1, 0, 0],
        "repair_verified": True,
        "real_customer_validation": "not_run",
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
