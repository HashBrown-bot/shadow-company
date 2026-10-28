"""Inventory installed, locked dependencies and license files. Unknown metadata fails closed."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

KNOWN = {
    "MIT",
    "Apache-2.0",
    "BSD-3-Clause",
    "BSD-2-Clause",
    "ISC",
    "0BSD",
    "CC-BY-4.0",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
    "MPL-2.0",
    "PSF-2.0",
    "MIT OR Apache-2.0",
    "Apache-2.0 OR BSD-2-Clause",
}


def license_files(paths):
    values = []
    for path in paths:
        path = Path(path)
        if path.is_file():
            values.append({"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return sorted(values, key=lambda r: (r["name"], r["sha256"]))


def inventory():
    records = []
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        name = metadata["Name"]
        if name == "enterprise-simulation-platform":
            continue
        license_ = metadata.get("License-Expression") or metadata.get("License")
        files = [
            distribution.locate_file(p)
            for p in distribution.files or []
            if "license" in str(p).lower() and not str(p).endswith(".py")
        ]
        records.append(
            {
                "ecosystem": "python",
                "name": name,
                "version": distribution.version,
                "license": license_,
                "license_files": license_files(files),
            }
        )
    node = {}
    for pattern in ("*/node_modules/*/package.json", "*/node_modules/@*/*/package.json"):
        for path in Path("node_modules/.pnpm").glob(pattern):
            data = json.loads(path.read_text())
            identity = (data["name"], data["version"])
            files = [
                p
                for p in path.parent.iterdir()
                if p.name.lower().startswith(("license", "copying", "notice"))
            ]
            node[identity] = {
                "ecosystem": "node",
                "name": identity[0],
                "version": identity[1],
                "license": data.get("license"),
                "license_files": license_files(files),
            }
    records += list(node.values())
    unknown = [
        {k: r[k] for k in ("ecosystem", "name", "version", "license")}
        for r in records
        if r["license"] not in KNOWN
    ]
    reciprocal = [r for r in records if any(x in (r["license"] or "") for x in ("LGPL", "MPL", "CC-BY"))]
    return {
        "schema_version": "e9-license-inventory-1",
        "source": "installed package metadata and shipped license files",
        "python_count": sum(r["ecosystem"] == "python" for r in records),
        "node_count": len(node),
        "records": sorted(records, key=lambda r: (r["ecosystem"], r["name"], r["version"])),
        "unknown": unknown,
        "redistribution_review": [{k: r[k] for k in ("name", "version", "license")} for r in reciprocal],
        "scope": "本地依赖清单与许可识别；分发前仍需保留版权/许可并核对二进制依赖的相应义务。项目自身未指定对外开源许可；未开展生产发布。",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = inventory()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("python_count", "node_count", "unknown")}, ensure_ascii=False))
    return 2 if result["unknown"] or result["node_count"] == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
