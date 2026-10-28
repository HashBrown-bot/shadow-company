"""Real API client; JSON envelopes and strict 0/1/2/3 gate semantics."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from packages.contracts.config import ConfigSyntaxError, parse_yaml, safe_validation_errors
from packages.transport.access import client_headers


class CLIError(Exception):
    def __init__(self, code, message, details=None, exit_code=2):
        self.payload = {"code": code, "message": message, "details": details or []}
        self.exit_code = exit_code


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse may echo user-supplied text, so do not publish it (it may be a secret).
        raise CLIError("usage_error", "参数缺失或无效；使用 simctl <command> --help 查看用法")


def identifier(value):
    try:
        return str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("需要 UUID") from None


class Client:
    def __init__(self, args):
        origin = args.api_url.rstrip("/")
        if origin not in {"http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000"}:
            raise CLIError("boundary_error", "CLI 仅允许本机 8000 API，禁止向其他目标发送令牌")
        self.origin = origin
        self.headers = client_headers(args.token_file)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None

        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, method, path, body=None, query=None):
        url = self.origin + "/api/" + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        req = urllib.request.Request(
            url,
            method=method,
            headers=self.headers | {"Content-Type": "application/json"},
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with self.http.open(req, timeout=30) as response:
                data = response.read(32 * 1024 * 1024 + 1)
                if len(data) > 32 * 1024 * 1024:
                    raise CLIError("response_too_large", "报告超过客户端上限")
                if "text/html" in response.headers.get("Content-Type", ""):
                    return data.decode()
                return json.loads(data)
        except urllib.error.HTTPError as error:
            status = error.code
            # Server details have safe schema paths, but never trust arbitrary error echoes.
            raise CLIError(
                "http_" + str(status),
                {
                    401: "令牌缺失、撤销或过期",
                    403: "令牌没有项目/运行或操作权限",
                    404: "资源不存在或证据已过期",
                    409: "契约、幂等键或运行状态冲突",
                    422: "配置或请求校验失败",
                    503: "服务或数据库不可用",
                }.get(status, "API 请求失败；检查服务日志"),
            ) from None
        except (OSError, ValueError, urllib.error.URLError):
            raise CLIError(
                "infrastructure_error", "无法连接本机 API 或响应无效；检查启动、迁移与端口"
            ) from None


def config_file(path):
    try:
        if Path(path).stat().st_size > 131072:
            raise CLIError("config_too_large", "配置超过 128 KiB")
        return parse_yaml(Path(path).read_text())
    except ValidationError as error:
        raise CLIError(
            "validation_error", "配置字段或类型无效", safe_validation_errors(error.errors())
        ) from None
    except ConfigSyntaxError:
        raise CLIError("yaml_error", "YAML 语法无效、重复字段或包含不支持的内容") from None


def prepare(client, args):
    project, version = args.project, args.contract_version
    if args.config:
        config = config_file(args.config)
        if not project:
            project = client.request("POST", "projects", {"name": args.name})["id"]
        version = version or "cli-" + uuid4().hex
        client.request(
            "PUT",
            f"projects/{project}/contract",
            {"version": version, "config": config.model_dump(mode="json")},
        )
    if not project or not version:
        raise CLIError("usage_error", "提供配置文件，或同时指定 --project 与 --contract-version")
    preflight = client.request("POST", f"projects/{project}/preflight", {"contract_version": version})
    return project, version, preflight


def wait_report(client, project, run, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status = client.request("GET", f"runs/{run}", query={"project_id": project})
        if status["status"] in {"completed", "failed", "cancelled"}:
            return client.request("GET", f"runs/{run}/report", query={"project_id": project})
        time.sleep(0.2)
    raise CLIError(
        "wait_timeout",
        "等待超时；运行尚未确认完成，可用 report 继续读取",
        [{"project_id": project, "run_id": run}],
        3,
    )


def parser():
    root = Parser(
        prog="simctl",
        description="本机仿真平台。退出码：0 所选 gate 通过；1 业务失败；2 配置/基础设施错误；3 证据不足/取消/预算未完成。默认输出 JSON。",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="机器可读 JSON（默认）")
    common.add_argument("--api-url", default=os.environ.get("SIM_API_URL", "http://127.0.0.1:8000"))
    common.add_argument(
        "--token-file",
        default=os.environ.get("SIM_TOKEN_FILE", ".local/access/operator.token"),
        help="0600 令牌文件；不接受命令行明文令牌",
    )
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("validate", "preflight", "run", "report", "replay", "compare"):
        p = sub.add_parser(name, parents=[common])
        if name in {"validate", "preflight", "run"}:
            p.add_argument("config", nargs=None if name == "validate" else "?")
        if name != "validate":
            p.add_argument("--project", type=identifier, required=name not in {"run", "preflight"})
        if name in {"run", "preflight"}:
            p.add_argument("--contract-version")
            p.add_argument("--name", default="示例 · simctl 本机运行")
        if name in {"run", "report", "replay", "compare"}:
            p.add_argument("--gate", choices=["selected", "suite"], default="selected")
            p.add_argument(
                "--strict",
                action="store_true",
                default=True,
                help="严格检查始终开启，必需规则全为不适用不能通过",
            )
            p.add_argument("--output", help="保存数据文件；不会覆盖已有文件")
        if name in {"run", "replay"}:
            p.add_argument("--wait-seconds", type=float, default=180)
            p.add_argument("--idempotency-key", default=None)
        if name == "run":
            p.add_argument("--scenarios", default=",".join(f"S{i:02}" for i in range(1, 21)))
            p.add_argument(
                "--suite-scope", choices=["e4_core_10", "e6_core_20", "e7_core_20"], default="e6_core_20"
            )
        if name == "report":
            p.add_argument("--run", type=identifier, required=True)
            p.add_argument("--format", choices=["json", "html"], default="json")
        if name == "replay":
            p.add_argument("--source", type=identifier, required=True)
            p.add_argument("--mode", choices=["history", "input", "controlled"], default="input")
            p.add_argument("--target-contract")
            p.add_argument("--target-version", choices=["buggy", "fixed"])
        if name == "compare":
            p.add_argument("--source", type=identifier, required=True)
            p.add_argument("--target", type=identifier, required=True)
    return root


def execute(args):
    if args.command == "validate":
        config = config_file(args.config)
        return 0, {
            "validation_gate": "pass",
            "content_hash": config.content_hash(),
            "preflight": "not_performed",
            "business_verdict": "inconclusive",
        }
    if hasattr(args, "wait_seconds") and not 0 < args.wait_seconds <= 3600:
        raise CLIError("usage_error", "--wait-seconds 必须在 0 到 3600 秒之间")
    client = Client(args)
    if args.command in {"preflight", "run"}:
        project, version, preflight = prepare(client, args)
        if args.command == "preflight" or not preflight["passed"]:
            return (0 if preflight["passed"] else 2), {
                "project_id": project,
                "contract_version": version,
                "preflight": preflight,
            }
        submitted = client.request(
            "POST",
            "runs",
            {
                "project_id": project,
                "contract_version": version,
                "idempotency_key": args.idempotency_key or str(uuid4()),
                "suite_scope": args.suite_scope,
                "scenarios": args.scenarios.split(","),
            },
        )
        run = submitted["run_id"]
    elif args.command == "replay":
        project = args.project
        body = {"project_id": project, "mode": args.mode, "reuse_product_outputs": False}
        if args.mode == "history":
            if args.target_contract or args.target_version:
                raise CLIError("usage_error", "history 不接受目标版本")
            data = client.request("POST", f"runs/{args.source}/replay", body)
            return 0, {"history_read_gate": "pass", "business_gate": "not_evaluated", "history": data}
        if not args.target_contract or not args.target_version:
            raise CLIError("usage_error", "输入重放必须指定 --target-contract 和 --target-version")
        preflight = client.request(
            "POST", f"projects/{project}/preflight", {"contract_version": args.target_contract}
        )
        if not preflight["passed"]:
            return 2, preflight
        body |= {
            "target_contract_version": args.target_contract,
            "target_product_version": args.target_version,
            "idempotency_key": args.idempotency_key or str(uuid4()),
        }
        run = client.request("POST", f"runs/{args.source}/replay", body)["run_id"]
    elif args.command == "compare":
        data = client.request(
            "GET",
            f"runs/{args.source}/compare",
            query={"project_id": args.project, "other_run_id": args.target},
        )
        gate = data["ci_gates"][args.gate]
        return gate["exit_code"], {
            "target_gate": data["target_ci_gates"][args.gate],
            "comparison": data,
        }
    else:
        project, run = args.project, args.run
    try:
        data = wait_report(client, project, run, getattr(args, "wait_seconds", 0.01))
    except KeyboardInterrupt:
        client.request("POST", f"runs/{run}/cancel", query={"project_id": project})
        raise CLIError(
            "cancelled", "已请求取消；保留在途操作后果", [{"project_id": project, "run_id": run}], 3
        ) from None
    gate = data.get("ci_gates", {}).get(args.gate)
    if not gate:
        raise CLIError("gate_unavailable", "该历史报告没有严格 gate 证据", exit_code=3)
    if getattr(args, "format", None) == "html":
        if not args.output:
            raise CLIError("usage_error", "HTML 导出需指定 --output")
        data = client.request("GET", f"runs/{run}/report", query={"project_id": project, "format": "html"})
    return gate["exit_code"], data


def main(argv=None):
    args = None
    try:
        args = parser().parse_args(argv)
        if getattr(args, "output", None) and Path(args.output).exists():
            raise CLIError("output_exists", "输出文件已存在；请指定新文件以保留已有产物")
        code, data = execute(args)
        if getattr(args, "output", None):
            with Path(args.output).open("x") as f:
                f.write(
                    data
                    if isinstance(data, str)
                    else json.dumps(data, ensure_ascii=False, indent=2, default=str)
                )
            data = {"artifact": args.output, "gate_exit_code": code}
        envelope = {"schema_version": "simctl-1", "command": args.command, "exit_code": code, "data": data}
    except CLIError as error:
        code = error.exit_code
        envelope = {"schema_version": "simctl-1", "exit_code": code, "error": error.payload}
    except (OSError, ValueError, KeyError, TypeError):
        code = 2
        envelope = {
            "schema_version": "simctl-1",
            "exit_code": code,
            "error": {"code": "local_error", "message": "本地文件、令牌权限或响应格式错误；未输出秘密"},
        }
    except KeyboardInterrupt:
        code = 3
        envelope = {
            "schema_version": "simctl-1",
            "exit_code": code,
            "error": {"code": "interrupted", "message": "客户端已中断，运行未确认完成"},
        }
    print(json.dumps(envelope, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
