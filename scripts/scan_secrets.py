"""Offline, high-confidence credential scan. Reports paths, never matched values."""

import json
import re
import subprocess
from pathlib import Path

PATTERNS = {
    "local_access_token": re.compile(r"(?<![A-Za-z0-9_-])sim_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "cloud_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "provider_api_key": re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}\b"),
    "github_token": re.compile(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{30,}\b"),
    "bearer_value": re.compile(r"(?i)bearer\s+[A-Za-z0-9_.-]{24,}"),
}


def main():
    paths = (
        subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"])
        .decode()
        .split("\0")
    )
    findings, count = [], 0
    for name in paths:
        path = Path(name)
        if not name or not path.is_file() or path.suffix in {".docx", ".png"}:
            continue
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            continue
        count += 1
        for kind, pattern in PATTERNS.items():
            if pattern.search(content):
                findings.append({"file": name, "kind": kind})
    print(
        json.dumps(
            {
                "scanned_text_files": count,
                "findings": findings,
                "scope": "repository source and text acceptance artifacts; binary originals and screenshots manually reviewed",
            },
            ensure_ascii=False,
        )
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
