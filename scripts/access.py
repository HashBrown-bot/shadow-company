"""Local operator token provisioning. Never writes token values to terminal output."""

import argparse
import json
from pathlib import Path

from packages.transport.access import bootstrap, issue, private_read, write_private


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=".local/access")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap")
    create = sub.add_parser("issue")
    create.add_argument("--output", required=True)
    create.add_argument("--projects", required=True, help="comma-separated UUIDs or * for local operator")
    create.add_argument("--permissions", default="read", help="read,run,evidence,raw,admin")
    create.add_argument("--runs", help="optional comma-separated run UUIDs; prohibits creating new runs")
    create.add_argument("--ttl", type=int, default=86400)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("id")
    args = parser.parse_args()
    registry = Path(args.directory) / "access-grants.json"
    try:
        if args.command == "bootstrap":
            server, token = bootstrap(args.directory)
            result = {"registry": server, "token_file": token, "note": "0600；令牌不打印；默认有效期 24 小时"}
        elif args.command == "issue":
            result = issue(
                registry,
                args.output,
                projects=args.projects.split(","),
                permissions=args.permissions.split(","),
                runs=args.runs.split(",") if args.runs else None,
                ttl=args.ttl,
            )
        else:
            data = json.loads(private_read(registry))
            grant = next(g for g in data["grants"] if g["id"] == args.id)
            grant["revoked"] = True
            write_private(registry, json.dumps(data, indent=2) + "\n")
            result = {"revoked": args.id}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, StopIteration):
        print(
            json.dumps(
                {"error": "访问配置操作失败；核对路径、权限、ID 和有效期；未输出秘密"}, ensure_ascii=False
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
