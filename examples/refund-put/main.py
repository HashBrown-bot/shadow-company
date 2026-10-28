"""Independent refund application. Approval policy and product state belong only here."""

import json
import os
import time
from datetime import datetime, timezone
from threading import Event
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from packages.contracts.config import Model
from packages.transport.build import service_build
from packages.transport.controls import BarrierPlan, EntryBarriers, audit, install_controls, match_fault
from packages.transport.example import Callback, Minor, Refund, Seed, install_errors, lock_scope, scope_exists
from packages.transport.http import BoundaryError, SafeHTTP
from packages.transport.security import (
    Scope,
    authorize,
    canonical,
    digest,
    headers,
    test_only,
    verify_signature,
)
from services.api.database import make_engine

THRESHOLD = 200000
PROVIDER = os.environ.get("EXAMPLE_PROVIDER_ORIGIN", "http://127.0.0.1:8002")
ACTIONS = {
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


class Amendment(Model):
    amount_minor: Minor


class Behavior(Model):
    variant: Literal["fixed", "buggy", "false_success"]


def snapshot(row):
    return {k: row[k] for k in ["refund_id", "amount_minor", "currency", "recipient", "version"]}


def create_app(engine=None):
    db = engine if engine is not None else make_engine()
    app = FastAPI(title="独立示例 Refund PUT", version="0.3.0")
    build = service_build("refund-put")
    install_errors(app)
    install_controls(app, db, "refund_put", "put_admin")
    barriers = EntryBarriers(db)

    @app.middleware("http")
    async def call_evidence(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/refunds"):
            try:
                scope, role = authorize(request, "support", "approver", "customer_a", "customer_b")
            except HTTPException:
                return response
            with db.begin() as c:
                variant = c.execute(
                    text("SELECT behavior FROM refund_put.namespaces WHERE project_id=:p AND run_id=:r"),
                    scope.params,
                ).scalar()
                if variant:
                    audit(
                        c,
                        "refund_put",
                        scope,
                        "business_call",
                        {
                            "method": request.method,
                            "path": request.url.path,
                            "role": role,
                            "variant": variant,
                            "build_hash": build["content_hash"],
                            "status": response.status_code,
                        },
                    )
                    response.headers["X-PUT-Version"] = variant
                    response.headers["X-PUT-Build-Hash"] = build["content_hash"]
        return response

    @app.post("/test/barriers")
    def set_barrier(body: BarrierPlan, request: Request):
        test_only()
        scope, _ = authorize(request, "put_admin")
        barriers.configure(scope, body)
        return {"configured": True}

    @app.post("/refunds/{refund_id}/cancel")
    def cancel(refund_id: str, request: Request):
        scope, _ = authorize(request, "support")
        group = request.headers.get("X-Sim-Barrier")
        if group:
            test_only()
        barriers.wait(scope, group, refund_id)
        with db.begin() as c:
            lock_scope(c, scope, "put")
            row = read(c, scope, refund_id)
            # Completed money wins; cancellation never erases an in-flight consequence.
            if row["status"] not in {"succeeded", "reconciliation_required", "execution_pending"}:
                c.execute(
                    text(
                        "UPDATE refund_put.refunds SET status='cancelled' WHERE project_id=:p AND run_id=:r AND refund_id=:id"
                    ),
                    scope.params | {"id": refund_id},
                )
            return read(c, scope, refund_id)

    def read(c, scope, identifier):
        row = (
            c.execute(
                text("SELECT * FROM refund_put.refunds WHERE project_id=:p AND run_id=:r AND refund_id=:id"),
                scope.params | {"id": identifier},
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "退款不存在")
        return dict(row)

    def behavior(c, scope):
        return c.execute(
            text("SELECT behavior FROM refund_put.namespaces WHERE project_id=:p AND run_id=:r"),
            scope.params,
        ).scalar_one()

    @app.get("/health")
    def health():
        with db.connect() as c:
            c.execute(text("SELECT 1 FROM refund_put.refunds LIMIT 0"))
        return {
            "service": "refund-put",
            "example": True,
            "phase": "E5",
            "status": "ok",
            "business_execution": "persistent",
        }

    @app.get("/capabilities")
    def capabilities(request: Request):
        authorize(request, "support", "approver", "put_admin")
        return {
            "example": True,
            "version": "fixed",
            "supported_versions": ["fixed", "buggy"],
            "adapter": "http_refund_v1",
            "actions": ACTIONS,
            "reset_path": "/test/reset",
            "seed_path": "/test/seed",
            "clock_support": ["realtime", "event_compressed"],
            "approval_threshold_minor": THRESHOLD,
            "threshold_operator": "gt",
            "partial_refunds_allowed": True,
            "provider_origin": PROVIDER,
            "test_mode": os.environ.get("EXAMPLE_TEST_MODE") == "1",
            "build": build,
            "replay_controls": ["new_namespace", "semantic_faults", "entry_barrier"],
        }

    @app.get("/identity")
    def identity(request: Request):
        scope, role = authorize(request, "support", "approver", "customer_a", "customer_b")
        permissions = {
            "support": ["request_refund", "execute_refund", "read_refund", "amend_refund"],
            "approver": ["approve_refund", "read_refund"],
            "customer_a": ["read_own_refund"],
            "customer_b": ["read_own_refund"],
        }
        return scope.model_dump() | {"role": role, "identity_id": role, "permissions": permissions[role]}

    @app.post("/test/seed")
    def seed(body: Seed, request: Request):
        test_only()
        scope, _ = authorize(request, "put_admin")
        data = body.model_dump(mode="json")
        with db.begin() as c:
            lock_scope(c, scope, "put")
            old = c.execute(
                text("SELECT snapshot FROM refund_put.namespaces WHERE project_id=:p AND run_id=:r"),
                scope.params,
            ).scalar()
            if old is not None:
                if old != data:
                    raise HTTPException(409, "命名空间已存在不同快照")
                return {"snapshot_hash": digest(data)}
            c.execute(
                text(
                    "INSERT INTO refund_put.namespaces (project_id,run_id,snapshot) VALUES (:p,:r,CAST(:s AS jsonb))"
                ),
                scope.params | {"s": canonical(data)},
            )
            for payment in body.payments:
                c.execute(
                    text(
                        "INSERT INTO refund_put.payments (project_id,run_id,payment_id,amount_minor,currency) VALUES (:p,:r,:payment_id,:amount_minor,:currency)"
                    ),
                    scope.params | payment.model_dump(),
                )
        return {"snapshot_hash": digest(data)}

    @app.post("/test/behavior")
    def set_behavior(body: Behavior, request: Request):
        test_only()
        scope, _ = authorize(request, "put_admin")
        with db.begin() as c:
            lock_scope(c, scope, "put")
            scope_exists(c, "refund_put", scope)
            if c.execute(
                text("SELECT 1 FROM refund_put.refunds WHERE project_id=:p AND run_id=:r LIMIT 1"),
                scope.params,
            ).scalar():
                raise HTTPException(409, "已有业务后不可切换示例行为")
            c.execute(
                text("UPDATE refund_put.namespaces SET behavior=:b WHERE project_id=:p AND run_id=:r"),
                scope.params | {"b": body.variant},
            )
        return {"configured": True}

    @app.post("/test/reset")
    def reset(request: Request):
        test_only()
        scope, _ = authorize(request, "put_admin")
        with db.begin() as c:
            lock_scope(c, scope, "put")
            counts = {}
            for table in ["audit", "fault_plans", "receipts", "refunds", "payments", "namespaces"]:
                counts[table] = c.execute(
                    text(f"DELETE FROM refund_put.{table} WHERE project_id=:p AND run_id=:r"), scope.params
                ).rowcount
        return {"reset": True, "removed": counts}

    @app.post("/refunds", status_code=201)
    def create(body: Refund, request: Request):
        scope, role = authorize(request, "support")
        with db.begin() as c:
            lock_scope(c, scope, "put")
            scope_exists(c, "refund_put", scope)
            payment = (
                c.execute(
                    text(
                        "SELECT * FROM refund_put.payments WHERE project_id=:p AND run_id=:r AND payment_id=:payment_id"
                    ),
                    scope.params | body.model_dump(),
                )
                .mappings()
                .first()
            )
            if not payment:
                raise HTTPException(404, "支付不存在")
            if payment["currency"] != body.currency:
                raise HTTPException(409, "币种不一致")
            params = (
                scope.params
                | body.model_dump()
                | {
                    "status": "approval_pending" if body.amount_minor > THRESHOLD else "requested",
                    "role": role,
                }
            )
            old = (
                c.execute(
                    text(
                        "SELECT * FROM refund_put.refunds WHERE project_id=:p AND run_id=:r AND refund_id=:refund_command_id"
                    ),
                    params,
                )
                .mappings()
                .first()
            )
            if old:
                if any(
                    old[k] != getattr(body, k)
                    for k in ["payment_id", "amount_minor", "currency", "recipient"]
                ):
                    raise HTTPException(409, "指令 ID 已用于不同参数")
                return dict(old)
            c.execute(
                text("""INSERT INTO refund_put.refunds
              (project_id,run_id,refund_id,payment_id,amount_minor,currency,recipient,status,created_by)
              VALUES (:p,:r,:refund_command_id,:payment_id,:amount_minor,:currency,:recipient,:status,:role)"""),
                params,
            )
            return read(c, scope, body.refund_command_id)

    @app.get("/refunds/{refund_id}")
    def query(refund_id: str, request: Request):
        scope, role = authorize(request, "support", "approver", "customer_a", "customer_b")
        with db.connect() as c:
            row = read(c, scope, refund_id)
            if role.startswith("customer_") and row["owner_id"] != role:
                raise HTTPException(403, "无权查看该退款")
            return row

    @app.patch("/refunds/{refund_id}")
    def amend(refund_id: str, body: Amendment, request: Request):
        scope, _ = authorize(request, "support")
        with db.begin() as c:
            lock_scope(c, scope, "put")
            row = read(c, scope, refund_id)
            if row["status"] == "succeeded":
                raise HTTPException(409, "已执行指令不可修改")
            approval = row["approval"] if behavior(c, scope) == "buggy" else None
            c.execute(
                text("""UPDATE refund_put.refunds SET amount_minor=:amount,version=version+1,
                approval=CAST(:approval AS jsonb),status=:status
                WHERE project_id=:p AND run_id=:r AND refund_id=:id"""),
                scope.params
                | {
                    "id": refund_id,
                    "amount": body.amount_minor,
                    "approval": canonical(approval),
                    "status": "approval_pending" if body.amount_minor > THRESHOLD else "requested",
                },
            )
            return read(c, scope, refund_id)

    @app.post("/refunds/{refund_id}/approve")
    def approve(refund_id: str, request: Request):
        scope, role = authorize(request, "approver")
        with db.begin() as c:
            row = read(c, scope, refund_id)
            fault = match_fault(
                c,
                "refund_put",
                scope,
                refund_id,
                1,
                {"approver_offline"},
                {
                    "operation": "approve_snapshot",
                    "state": row["status"],
                    "fields": {k: row[k] for k in ("payment_id", "amount_minor", "currency", "recipient")}
                    | {"command_version": row["version"]},
                },
            )
            if fault and not fault.get("fixture_mismatch"):
                audit(
                    c,
                    "refund_put",
                    scope,
                    "fault_hit",
                    fault | {"stage": "approval_unavailable", "available": False},
                )
        if fault and fault.get("fixture_mismatch"):
            return JSONResponse(status_code=409, content={"error": "fixture_mismatch"})
        if fault:
            return JSONResponse(status_code=423, content={"error": "approver_offline", "available": False})
        with db.begin() as c:
            lock_scope(c, scope, "put")
            row = read(c, scope, refund_id)
            if row["status"] == "succeeded":
                raise HTTPException(409, "已执行")
            approval = snapshot(row) | {
                "approved_by": role,
                "approved": True,
                "approval_id": str(uuid4()),
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }
            c.execute(
                text(
                    "UPDATE refund_put.refunds SET approval=CAST(:a AS jsonb),status='approved' WHERE project_id=:p AND run_id=:r AND refund_id=:id"
                ),
                scope.params | {"id": refund_id, "a": canonical(approval)},
            )
            return read(c, scope, refund_id)

    @app.post("/refunds/{refund_id}/execute")
    def execute(refund_id: str, request: Request):
        scope, _ = authorize(request, "support")
        group = request.headers.get("X-Sim-Barrier")
        if group:
            test_only()
        barriers.wait(scope, group, refund_id)
        with db.connect() as inspect:
            mode = behavior(inspect, scope)
            stale = read(inspect, scope, refund_id)
            balance = inspect.execute(
                text(
                    "SELECT refunded_minor FROM refund_put.payments WHERE project_id=:p AND run_id=:r AND payment_id=:id"
                ),
                scope.params | {"id": stale["payment_id"]},
            ).scalar_one()
        if group and mode == "buggy" and group.startswith("S17"):
            # Deliberately defective check-then-act uses the concurrently read balance.
            barriers.wait(scope, group, refund_id, "balance_read")
        with db.begin() as c:
            lock_scope(c, scope, "put")
            row = read(c, scope, refund_id)
            if row["status"] == "cancelled":
                return row
            if row["status"] == "succeeded" and mode != "buggy":
                return row
            if row["amount_minor"] > THRESHOLD:
                if not row["approval"] or (
                    mode != "buggy" and any(row["approval"].get(k) != v for k, v in snapshot(row).items())
                ):
                    raise HTTPException(409, "缺少同版本有效审批")
            payment = (
                c.execute(
                    text(
                        "SELECT * FROM refund_put.payments WHERE project_id=:p AND run_id=:r AND payment_id=:id FOR UPDATE"
                    ),
                    scope.params | {"id": row["payment_id"]},
                )
                .mappings()
                .one()
            )
            if (
                group
                and mode == "buggy"
                and group.startswith("S17")
                and balance + row["amount_minor"] > payment["amount_minor"]
            ):
                raise HTTPException(409, "累计退款超过余额")
            if mode != "buggy" and payment["refunded_minor"] + row["amount_minor"] > payment["amount_minor"]:
                raise HTTPException(409, "累计退款超过余额")
            payload = {k: row[k] for k in ["payment_id", "amount_minor", "currency", "recipient"]} | {
                "refund_command_id": refund_id,
                "idempotency_key": str(uuid4()) if mode == "buggy" else refund_id,
                "command_version": row["version"],
                "approval": row["approval"],
            }
            if mode == "false_success":
                c.execute(
                    text(
                        "UPDATE refund_put.refunds SET status='succeeded' WHERE project_id=:p AND run_id=:r AND refund_id=:id"
                    ),
                    scope.params | {"id": refund_id},
                )
                return read(c, scope, refund_id)
            retries = min(2, max(0, int(request.headers.get("X-Sim-Max-Retries", "0"))))
            for attempt in range(retries + 1):
                if attempt and mode == "buggy":
                    payload["idempotency_key"] = str(uuid4())
                sent = time.time()
                try:
                    response = SafeHTTP().request(
                        "POST",
                        PROVIDER,
                        "/executions",
                        headers=headers("provider_execute", scope),
                        body=payload,
                        timeout=0.35,
                    )
                    outcome = "http_response"
                except BoundaryError as error:
                    response = {"status": None, "body": {}}
                    outcome = "read_timeout" if "timeout" in str(error) else "connection_failure"
                audit(
                    c,
                    "refund_put",
                    scope,
                    "provider_attempt",
                    {
                        "command_id": refund_id,
                        "attempt": attempt + 1,
                        "idempotency_key": payload["idempotency_key"],
                        "outcome": outcome,
                        "status": response["status"],
                        "started_at": sent,
                        "ended_at": time.time(),
                    },
                )
                if response["status"] == 200:
                    break
                if response["status"] is None and mode != "buggy":
                    response = SafeHTTP().request(
                        "GET",
                        PROVIDER,
                        "/executions/" + payload["idempotency_key"],
                        headers=headers("provider_execute", scope),
                    )
                    audit(
                        c,
                        "refund_put",
                        scope,
                        "provider_reconciliation",
                        {
                            "command_id": refund_id,
                            "status": response["status"],
                            "entry_id": response["body"].get("entry_id"),
                        },
                    )
                    if response["status"] == 200:
                        break
                    if response["status"] != 404:
                        break
                if response["status"] == 429 and attempt < retries:
                    Event().wait(min(0.1, response["body"].get("retry_after_ms", 0) / 1000))
                elif response["status"] not in {None, 404, 429}:
                    break
            if response["status"] != 200:
                c.execute(
                    text(
                        "UPDATE refund_put.refunds SET status='reconciliation_required' WHERE project_id=:p AND run_id=:r AND refund_id=:id"
                    ),
                    scope.params | {"id": refund_id},
                )
                return read(c, scope, refund_id)
            c.execute(
                text(
                    "UPDATE refund_put.refunds SET status='succeeded',provider_entry_id=:e WHERE project_id=:p AND run_id=:r AND refund_id=:id"
                ),
                scope.params | {"e": UUID(response["body"]["entry_id"]), "id": refund_id},
            )
            c.execute(
                text(
                    "UPDATE refund_put.payments SET refunded_minor=refunded_minor+:amount WHERE project_id=:p AND run_id=:r AND payment_id=:id"
                ),
                scope.params | {"amount": row["amount_minor"], "id": row["payment_id"]},
            )
            return read(c, scope, refund_id)

    @app.post("/callbacks")
    async def callback(request: Request):
        body = await request.body()
        if len(body) > 65536:
            raise HTTPException(413, "回调过大")
        try:
            event = Callback.model_validate_json(body)
        except ValueError:
            raise HTTPException(422, "回调格式无效") from None
        scope = Scope(project_id=event.project_id, run_id=event.run_id)
        verify_signature(
            scope,
            request.headers.get("X-Webhook-Timestamp"),
            body,
            request.headers.get("X-Webhook-Signature"),
        )
        with db.begin() as c:
            lock_scope(c, scope, "put")
            scope_exists(c, "refund_put", scope)
            row = read(c, scope, event.refund_command_id)
            if (
                any(row[k] != getattr(event, k) for k in ["payment_id", "amount_minor", "currency"])
                or str(row["provider_entry_id"]) != str(event.entry_id)
                or event.status not in {"succeeded", "execution_pending"}
            ):
                raise HTTPException(409, "回调与已执行指令冲突")
            old = c.execute(
                text(
                    "SELECT digest FROM refund_put.receipts WHERE project_id=:p AND run_id=:r AND event_id=:e"
                ),
                scope.params | {"e": event.event_id},
            ).scalar()
            event_digest = digest(json.loads(body))
            if old and old != event_digest:
                raise HTTPException(409, "重复事件内容冲突")
            if not old and event.status == "execution_pending":
                if event.state_version != 1:
                    raise HTTPException(409, "中间态缺少旧版本证据")
                if behavior(c, scope) == "buggy":
                    c.execute(
                        text(
                            "UPDATE refund_put.refunds SET status='execution_pending' WHERE project_id=:p AND run_id=:r AND refund_id=:id"
                        ),
                        scope.params | {"id": event.refund_command_id},
                    )
            audit(
                c,
                "refund_put",
                scope,
                "callback_received",
                {
                    "event_id": str(event.event_id),
                    "command_id": event.refund_command_id,
                    "status": event.status,
                    "state_version": event.state_version,
                    "duplicate": bool(old),
                    "product_status": read(c, scope, event.refund_command_id)["status"],
                },
            )
            if not old:
                c.execute(
                    text("INSERT INTO refund_put.receipts VALUES (:p,:r,:e,:h,CAST(:v AS jsonb))"),
                    scope.params | {"e": event.event_id, "h": event_digest, "v": body.decode()},
                )
        return {"accepted": True, "duplicate": old is not None}

    return app


app = create_app()
