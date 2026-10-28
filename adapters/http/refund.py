"""Standard actions mapped to the explicitly reviewed example contract."""

import time
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from packages.evidence.store import append
from packages.transport.http import BoundaryError, SafeHTTP
from packages.transport.security import canonical, headers

EXPECTED_ACTIONS = {
    "request_refund": {"method": "POST", "path": "/refunds", "semantic": "create_application"},
    "approve_refund": {
        "method": "POST",
        "path": "/refunds/{refund_id}/approve",
        "semantic": "approve_snapshot",
    },
    "execute_refund": {
        "method": "POST",
        "path": "/refunds/{refund_id}/execute",
        "semantic": "request_execution",
    },
    "read_refund": {"method": "GET", "path": "/refunds/{refund_id}", "semantic": "observe_application"},
}


def validate_example(config):
    if config.product.id != "refund_demo" or config.product.version not in {"fixed", "buggy"}:
        raise BoundaryError("仅开放已审阅的 fixed/buggy 本机示例；其他目标尚未接入")
    if (
        config.product.credentials.support != "secret://demo/support"
        or config.product.credentials.approver != "secret://demo/approver"
    ):
        raise BoundaryError("E3 不解析真实凭据；仅允许生成的示例身份引用")
    if config.product.actions.model_dump() != EXPECTED_ACTIONS:
        raise BoundaryError("动作映射未通过示例语义审阅")
    if (config.product.reset.endpoint, config.provider.reset_path, config.provider.ledger_path) != (
        "/test/reset",
        "/test/reset",
        "/test/ledger",
    ):
        raise BoundaryError("reset/ledger 路径与示例契约不一致")
    if config.product.base_url == config.provider.base_url:
        raise BoundaryError("PUT 与 provider 必须是独立 origin")
    for origin, port in [(config.product.base_url, 8001), (config.provider.base_url, 8002)]:
        parsed, _ = SafeHTTP().resolve(origin)
        if parsed.port != port:
            raise BoundaryError("服务 origin 角色不匹配")
    env = config.environment
    if env.approval_threshold_minor != 200000 or not env.partial_refunds_allowed:
        raise BoundaryError("示例 PUT 仅声明 gt 200000 与部分退款政策")


class RefundAdapter:
    def __init__(self, db, scope, config):
        self.db, self.scope, self.config = db, scope, config
        self.http = SafeHTTP()

    def request(self, *args, **kwargs):
        return self.http.request(*args, **kwargs)

    def call(
        self,
        target,
        role,
        method,
        path,
        body=None,
        operation=None,
        external_id="protocol",
        *,
        context=None,
        extra_headers=None,
        after_remote=None,
        timeout=5,
    ):
        origin = self.config.product.base_url if target == "put" else self.config.provider.base_url
        request_headers = headers(role, self.scope) | (extra_headers or {})
        start = time.monotonic()
        self_start = datetime.now(timezone.utc).isoformat()
        event_id, action_id = uuid4(), uuid4()
        if context:
            event_id, action_id = context["event_id"], context["action_id"]
        if operation and not context:
            with self.db.begin() as c:
                c.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"),
                    {"k": "events:" + self.scope.namespace},
                )
                seq = c.execute(
                    text(
                        "SELECT COALESCE(max(ingress_sequence),0)+1 FROM events WHERE project_id=:p AND run_id=:r"
                    ),
                    self.scope.params,
                ).scalar_one()
                c.execute(
                    text("""INSERT INTO events (project_id,run_id,event_id,business_object_id,simulation_time,wall_time,ingress_sequence,payload)
                  VALUES (:p,:r,:e,:obj,now(),now(),:seq,CAST(:v AS jsonb))"""),
                    self.scope.params
                    | {
                        "e": event_id,
                        "obj": external_id,
                        "seq": seq,
                        "v": canonical({"operation": operation}),
                    },
                )
                c.execute(
                    text("""INSERT INTO actions (project_id,run_id,action_id,event_id,actor_id,operation,request_ref,start_time)
                  VALUES (:p,:r,:a,:e,:role,:op,:ref,now())"""),
                    self.scope.params
                    | {
                        "a": action_id,
                        "e": event_id,
                        "role": role,
                        "op": operation,
                        "ref": f"private://postgres/{self.scope.namespace}/{event_id}",
                    },
                )
        try:
            result = self.request(method, origin, path, headers=request_headers, body=body, timeout=timeout)
        except BoundaryError as error:
            result = {"status": None, "headers": {}, "body": {"error": "transport_error"}}
            self.record(
                target,
                path,
                method,
                request_headers,
                body,
                result,
                external_id,
                start,
                action_id if (operation or context) else None,
                role,
            )
            raise error
        if after_remote:
            after_remote()
        result["timing"] = {
            "started_at": self_start,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "http_duration_ms": round((time.monotonic() - start) * 1000, 3),
        }
        self.record(
            target,
            path,
            method,
            request_headers,
            body,
            result,
            external_id,
            start,
            action_id if (operation or context) else None,
            role,
        )
        return result

    def record(
        self, target, path, method, request_headers, body, result, external_id, start, action_id, role
    ):
        source = (
            "put"
            if target == "put"
            else ("provider_ledger" if path == self.config.provider.ledger_path else "provider_control")
        )
        kind = "product_observation" if target == "put" else "dependency_evidence"
        with self.db.begin() as c:
            observation_id = append(
                c,
                self.scope,
                source,
                external_id,
                kind,
                {
                    "actor_id": role,
                    "request": {"method": method, "path": path, "headers": request_headers, "body": body},
                    "response": result,
                    "duration_ms": round((time.monotonic() - start) * 1000, 3),
                },
            )
            if action_id:
                from packages.simulator.jobs import journal

                sequence = journal(
                    c,
                    self.scope,
                    "action_finished",
                    {"action_id": str(action_id), "observation_id": observation_id},
                )
                c.execute(
                    text(
                        "UPDATE actions SET end_time=clock_timestamp(),end_sequence=:seq,request_ref=:ref WHERE project_id=:p AND run_id=:r AND action_id=:a"
                    ),
                    self.scope.params
                    | {
                        "a": action_id,
                        "seq": sequence,
                        "ref": f"private://postgres/{self.scope.namespace}/{observation_id}",
                    },
                )

    def action(self, operation, refund_id, body=None, role=None):
        endpoint = getattr(self.config.product.actions, operation)
        path = endpoint.path.replace("{refund_id}", refund_id)
        role = role or ("approver" if operation == "approve_refund" else "support")
        return self.call("put", role, endpoint.method, path, body, operation, refund_id)

    def ledger(self):
        return self.call("provider", "provider_reader", "GET", self.config.provider.ledger_path)
