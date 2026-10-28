"""Install and run README in a new source copy, empty venv/node_modules and fresh PostgreSQL.

Only package caches may be reused; no application state, credentials, .env,
or installed environment is copied. No external scheduler or deployment is created.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="docs/evidence/e9-clean")
    parser.add_argument(
        "--online", action="store_true", help="Allow locked package/registry metadata downloads"
    )
    args = parser.parse_args()
    evidence = (ROOT / args.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    directory = ROOT / ".local" / ("e9-clean-" + uuid4().hex)
    directory.mkdir()
    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    for name in names:
        if not name or name.startswith("docs/evidence/"):
            continue
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            continue
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    runtime = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
    env = {k: os.environ[k] for k in ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL") if k in os.environ}
    env["PATH"] = os.pathsep.join(
        [
            str(ROOT / ".venv/bin"),
            str(runtime / "node/bin"),
            str(runtime / "bin/fallback"),
            env.get("PATH", ""),
        ]
    )
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    env["UV_PYTHON_DOWNLOADS"] = "never"
    env["UV_PYTHON"] = sys._base_executable
    env["ACCEPTANCE_EVIDENCE_DIR"] = str(evidence / "verification")
    env["SIM_PNPM_STORE"] = str(directory / ".local/pnpm-store")
    # Copy public dependency cache; keep the source project's cache and application state untouched.
    shutil.copytree(ROOT / ".local/pnpm-store", directory / ".local/pnpm-store")
    uv = str(ROOT / ".venv/bin/uv")
    pnpm = shutil.which("pnpm", path=env["PATH"])

    def command(name, argv):
        with (evidence / (name + ".txt")).open("w") as log:
            subprocess.run(argv, cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(name + " passed", flush=True)

    def metadata():
        paths = [ROOT / ".env", ROOT / ".local/postgres"]
        return {
            str(p.relative_to(ROOT)): {
                "exists": p.exists(),
                "mtime_ns": p.stat().st_mtime_ns if p.exists() else None,
            }
            for p in paths
        }

    original = metadata()
    command("git-isolated", ["git", "init"])
    offline = [] if args.online else ["--offline"]
    command(
        "install-python", [uv, "sync", "--frozen", *offline, "--cache-dir", str(ROOT / ".local/uv-cache")]
    )
    command(
        "install-node",
        [pnpm, "install", "--frozen-lockfile", *offline, "--store-dir", env["SIM_PNPM_STORE"]],
    )
    shutil.copy2(directory / ".env.example", directory / ".env")
    python = str(directory / ".venv/bin/python")
    command("installed-cli", [str(directory / ".venv/bin/simctl"), "--help"])
    with (evidence / "readme-startup.txt").open("w") as log:
        dev = subprocess.Popen(
            [python, "scripts/dev.py"],
            cwd=directory,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 90
            with httpx.Client(trust_env=False, timeout=2) as http:
                while time.monotonic() < deadline and dev.poll() is None:
                    try:
                        if http.get("http://127.0.0.1:3000").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("README startup did not become ready")
            command("readme-demo", [python, "-m", "scripts.demo_e9", "--output-dir", str(evidence / "demo")])
        finally:
            if dev.poll() is None:
                os.killpg(dev.pid, signal.SIGTERM)
                dev.wait(timeout=40)
    command("verification", [python, "-m", "scripts.verify_e9"])
    assert original == metadata(), "source .env/development database metadata changed"
    (evidence / "clean-environment.json").write_text(
        json.dumps(
            {
                "result": "passed",
                "directory": str(directory),
                "fresh_venv": True,
                "fresh_node_modules": True,
                "empty_database_migration": True,
                "cache_reused": "downloaded dependency archives only; locked install actually executed",
                "offline_install": not args.online,
                "source_environment_unchanged": original == metadata(),
                "model_credentials_present": False,
                "external_ci": "not_run",
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
