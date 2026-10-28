"""Content provenance of reviewed source files only. Never inspect environment credentials."""

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from functools import lru_cache
from pathlib import Path

from packages.transport.security import digest

ROOT = Path(__file__).resolve().parents[2]


def files_hash(paths):
    files = {}
    for name in paths:
        path = ROOT / name
        for file in sorted(path.rglob("*")) if path.is_dir() else [path]:
            if file.is_file() and (
                not path.is_dir() or file.suffix in {".py", ".ts", ".tsx", ".css", ".json"}
            ):
                files[str(file.relative_to(ROOT))] = hashlib.sha256(file.read_bytes()).hexdigest()
    return {"content_hash": digest(files), "files": files}


def service_build(service):
    paths = [
        f"examples/{service}/main.py",
        "packages/transport",
        "packages/contracts",
        "services/api/database.py",
        "services/api/settings.py",
        "uv.lock",
    ]
    return {"version": "e6-example-1", **files_hash(paths)}


@lru_cache(maxsize=1)
def provenance():
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    dependencies = {
        d.metadata["Name"]: d.version for d in importlib.metadata.distributions() if d.metadata["Name"]
    }
    return {
        "code_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "working_tree": "content_hash_is_authoritative; uncommitted files included",
        "platform": files_hash(["packages", "services", "adapters", "migrations"]),
        "adapter": {"version": "http_refund_v1-e6-1", **files_hash(["adapters/http"])},
        "rules": {"version": "refund-v2", **files_hash(["packages/evaluators/refund.py"])},
        "put": service_build("refund-put"),
        "provider": service_build("payment-provider"),
        "web": files_hash(["apps/web/app"]),
        "dependencies": {
            "python": platform.python_version(),
            "web_declared": json.loads((ROOT / "apps/web/package.json").read_text())["dependencies"],
            "package_manager": json.loads((ROOT / "package.json").read_text())["packageManager"],
            "resolved": dict(sorted(dependencies.items())),
            "locks": files_hash(["uv.lock", "pnpm-lock.yaml"]),
            "os": platform.system(),
            "architecture": platform.machine(),
        },
    }


# Capture process-start provenance. Editing source while a service is running must not relabel its loaded code.
provenance()
