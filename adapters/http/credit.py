"""RPC credit-note wire mapping -> versioned canonical refund observations.

The original wire request/response remains alongside the projection; values are renamed,
never corrected or supplied from expected results. Provider evidence is untouched.
"""

from uuid import uuid4

from adapters.http.refund import EXPECTED_ACTIONS, RefundAdapter
from packages.transport.http import BoundaryError, SafeHTTP

FIELDS = {
    "refund_command_id": "noteNumber",
    "refund_id": "noteNumber",
    "payment_id": "chargeReference",
    "amount_minor": "units",
    "currency": "unitCurrency",
    "recipient": "payee",
    "version": "revision",
    "status": "phase",
    "approval": "authorization",
    "provider_entry_id": "settlementReference",
}
REVERSE = {v: k for k, v in FIELDS.items() if k != "refund_command_id"}


def rename(value, mapping):
    if isinstance(value, dict):
        return {mapping.get(k, k): rename(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [rename(v, mapping) for v in value]
    return value


def validate_credit(config):
    if config.product.id != "credit_note_demo" or config.product.version not in {"fixed", "buggy"}:
        raise BoundaryError("仅支持已审阅的本机贷项单示例")
    if (
        config.product.base_url != "http://127.0.0.1:8003"
        or config.provider.base_url != "http://127.0.0.1:8002"
    ):
        raise BoundaryError("贷项单示例 origin 未批准")
    if config.product.actions.model_dump() != EXPECTED_ACTIONS:
        raise BoundaryError("canonical refund observation 动作映射不一致")
    if config.product.credentials.model_dump() != {
        "support": "secret://demo/support",
        "approver": "secret://demo/approver",
    }:
        raise BoundaryError("仅支持生成的示例身份")
    if (config.product.reset.endpoint, config.provider.reset_path, config.provider.ledger_path) != (
        "/test/reset",
        "/test/reset",
        "/test/ledger",
    ):
        raise BoundaryError("未审阅的 reset 或账本映射")
    if (
        config.environment.approval_threshold_minor != 200000
        or not config.environment.partial_refunds_allowed
    ):
        raise BoundaryError("示例政策不匹配")
    for origin in (config.product.base_url, config.provider.base_url):
        SafeHTTP().resolve(origin)


class CreditAdapter(RefundAdapter):
    def request(self, method, origin, path, **kwargs):
        if origin == self.config.provider.base_url:
            result = self.http.request(method, origin, path, **kwargs)
            if path == "/test/seed" and result["status"] == 200:
                configured = self.http.request(
                    "POST",
                    origin,
                    "/test/callback-route",
                    headers=kwargs["headers"],
                    body={"origin": self.config.product.base_url},
                )
                if configured["status"] != 200:
                    raise BoundaryError("第二示例回调路由未配置")
            return result
        methods = {
            ("GET", "/capabilities"): "system.describe",
            ("GET", "/identity"): "identity.describe",
            ("POST", "/test/seed"): "sandbox.initialize",
            ("POST", "/test/reset"): "sandbox.purge",
            ("POST", "/test/behavior"): "sandbox.version",
            ("POST", "/refunds"): "notes.issue",
        }
        params = rename(kwargs.get("body") or {}, FIELDS)
        rpc = methods.get((method, path))
        if rpc is None and path.startswith("/refunds/"):
            parts = path.split("/")
            params["noteNumber"] = parts[2]
            rpc = (
                {"approve": "notes.authorize", "execute": "notes.settle", "cancel": "notes.cancel"}.get(
                    parts[3]
                )
                if len(parts) == 4
                else ("notes.fetch" if method == "GET" else "notes.revise")
            )
        if not rpc:
            raise BoundaryError("该 RPC 示例未实现此能力；不能假定通过")
        body = {"jsonrpc": "2.0", "id": str(uuid4()), "method": rpc, "params": params}
        wire = self.http.request("POST", origin, "/rpc", **(kwargs | {"body": body}))
        payload = wire["body"]
        if wire["status"] != 200:
            result = wire
        elif not isinstance(payload, dict) or payload.get("id") != body["id"] or "result" not in payload:
            raise BoundaryError("RPC 响应形状或关联 ID 错误")
        else:
            content = payload["result"]
            result = {
                "status": content["code"],
                "body": rename(content["document"], REVERSE),
                "headers": wire["headers"],
            }
        return result | {
            "wire": {"method": "POST", "path": "/rpc", "request": body, "response": wire},
            "normalization": "rpc_credit_v1 -> canonical_refund_observation_v1; rename only",
        }
