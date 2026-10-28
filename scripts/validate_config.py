"""Offline E2 validation helper, not the E9 simctl CLI."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from packages.contracts.config import ConfigSyntaxError, parse_yaml, safe_validation_errors


def main():
    parser = argparse.ArgumentParser(description="离线校验 V2 契约 YAML，不执行预检或业务")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        config = parse_yaml(args.path.read_text())
    except ValidationError as error:
        print(
            json.dumps(
                {
                    "valid": False,
                    "errors": safe_validation_errors(error.errors()),
                },
                ensure_ascii=False,
            )
        )
        return 2
    except (OSError, ConfigSyntaxError) as error:
        message = "无法读取配置文件" if isinstance(error, OSError) else str(error)
        print(json.dumps({"valid": False, "message": message}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "valid": True,
                "schema_version": config.schema_version,
                "content_hash": config.content_hash(),
                "preflight": "not_performed",
                "business_verdict": "inconclusive",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
