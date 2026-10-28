"""Independent example payment service. No PUT database reads and no evaluator answers."""

import os
import time
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from packages.contracts.config import Model
from packages.transport.build import service_build
from packages.transport.controls import (
    Delivery,
    DropBeforeCommit,
    LoseCommittedResponse,
    audit,
    install_controls,
    match_fault,
)
from packages.transport.example import Execute, Seed, install_errors, lock_scope, scope_exists
from packages.transport.http import BoundaryError, SafeHTTP
from packages.transport.security import authorize, canonical, digest, signature, test_only
from services.api.database import make_engine


class CallbackRoute(Model):
    origin: Literal["http://127.0.0.1:8001", "http://127.0.0.1:8003"]


def create_app(engine=None):
    db = engine if engine is not None else make_engine()
    app = FastAPI(title="独立示例 Payment Provider", version="0.3.0")
    build = service_build("payment-provider")
    install_errors(app)
    install_controls(app, db, "payment_provider", "provider_admin")

    @app.get("/health")
    def health():
        with db.connect() as c:
            c.execute(text("SELECT 1 FROM payment_provider.ledger LIMIT 0"))
        return {
            "service": "payment-provider",
            "example": True,
            "phase": "E5",
            "status": "ok",
            "ledger": "persistent",
        }

    @app.get("/capabilities")
    def capabilities(request: Request):
        authorize(request, "provider_reader", "provider_admin")
        return {
            "example": True,
            "adapter": "payment_stub_v1",
            "ledger_path": "/test/ledger",
            "reset_path": "/test/reset",
            "seed_path": "/test/seed",
            "clock_support": ["realtime", "event_compressed"],
            "idempotency_scope": "tenant_and_idempotency_key",
            "test_mode": os.environ.get("EXAMPLE_TEST_MODE") == "1",
            "build": build,
            "replay_controls": ["new_namespace", "semantic_faults", "callback_delivery"],
        }

    @app.post("/test/seed")
    def seed(body: Seed, request: Request):
        test_only()
        scope, _ = authorize(request, "provider_admin")
        data = body.model_dump(mode="json")
        with db.begin() as c:
            lock_scope(c, scope, "provider")
            old = c.execute(
                text("SELECT snapshot FROM payment_provider.namespaces WHERE project_id=:p AND run_id=:r"),
                scope.params,
            ).scalar()
            if old is not None:
                if old != data:
                    raise HTTPException(409, "命名空间已存在不同快照")
                return {"snapshot_hash": digest(data)}
            c.execute(
                text(
                    "INSERT INTO payment_provider.namespaces(project_id,run_id,snapshot) VALUES (:p,:r,CAST(:s AS jsonb))"
                ),
                scope.params | {"s": canonical(data)},
            )
            for payment in body.payments:
                c.execute(
                    text(
                        "INSERT INTO payment_provider.payments VALUES (:p,:r,:payment_id,:amount_minor,:currency)"
                    ),
                    scope.params | payment.model_dump(),
                )
        return {"snapshot_hash": digest(data)}

    @app.post("/test/callback-route")
    def callback_route(body: CallbackRoute, request: Request):
        test_only()
        scope, _ = authorize(request, "provider_admin")
        SafeHTTP().resolve(body.origin)
        with db.begin() as c:
            lock_scope(c, scope, "provider")
            scope_exists(c, "payment_provider", scope)
            if c.execute(
                text("SELECT 1 FROM payment_provider.ledger WHERE project_id=:p AND run_id=:r LIMIT 1"),
                scope.params,
            ).scalar():
                raise HTTPException(409, "已执行后不能更改回调接收方")
            c.execute(
                text(
                    "UPDATE payment_provider.namespaces SET put_origin=:origin WHERE project_id=:p AND run_id=:r"
                ),
                scope.params | {"origin": body.origin},
            )
        return {"configured": True}

    @app.post("/test/reset")
    def reset(request: Request):
        test_only()
        scope, _ = authorize(request, "provider_admin")
        with db.begin() as c:
            lock_scope(c, scope, "provider")
            counts = {}
            for table in ["audit", "fault_plans", "outbox", "ledger", "payments", "namespaces"]:
                counts[table] = c.execute(
                    text(f"DELETE FROM payment_provider.{table} WHERE project_id=:p AND run_id=:r"),
                    scope.params,
                ).rowcount
        return {"reset": True, "removed": counts}

    @app.get("/test/ledger")
    def ledger(request: Request):
        test_only()
        scope, _ = authorize(request, "provider_reader")
        with db.connect() as c:
            lock_scope(c, scope, "provider")
            payments = (
                c.execute(
                    text(
                        "SELECT * FROM payment_provider.payments WHERE project_id=:p AND run_id=:r ORDER BY payment_id"
                    ),
                    scope.params,
                )
                .mappings()
                .all()
            )
            rows = (
                c.execute(
                    text(
                        "SELECT * FROM payment_provider.ledger WHERE project_id=:p AND run_id=:r ORDER BY created_at,entry_id"
                    ),
                    scope.params,
                )
                .mappings()
                .all()
            )
            callbacks = (
                c.execute(
                    text(
                        "SELECT event_id,entry_id,put_delivered,platform_delivered,attempts FROM payment_provider.outbox WHERE project_id=:p AND run_id=:r ORDER BY event_id"
                    ),
                    scope.params,
                )
                .mappings()
                .all()
            )
        return {
            "project_id": str(scope.project_id),
            "run_id": str(scope.run_id),
            "complete": True,
            "payments": [dict(p) for p in payments],
            "entries": [dict(r) for r in rows],
            "callbacks": [dict(r) for r in callbacks],
        }

    @app.post("/executions")
    def execute(body: Execute, request: Request):
        scope, _ = authorize(request, "provider_execute")
        payload = body.model_dump()
        with db.begin() as c:
            scope_exists(c, "payment_provider", scope)
            lock_scope(c, scope, "provider")
            attempt = c.execute(
                text(
                    "SELECT count(*)+1 FROM payment_provider.audit WHERE project_id=:p AND run_id=:r AND kind='execution_received' AND payload->>'command_id'=:id"
                ),
                scope.params | {"id": body.refund_command_id},
            ).scalar_one()
            audit(
                c,
                "payment_provider",
                scope,
                "execution_received",
                {
                    "command_id": body.refund_command_id,
                    "idempotency_key": body.idempotency_key,
                    "attempt": attempt,
                    "build_hash": build["content_hash"],
                },
            )
            committed = c.execute(
                text(
                    "SELECT count(*) FROM payment_provider.ledger WHERE project_id=:p AND run_id=:r AND refund_command_id=:id"
                ),
                scope.params | {"id": body.refund_command_id},
            ).scalar_one()
            fault = match_fault(
                c,
                "payment_provider",
                scope,
                body.refund_command_id,
                attempt,
                {"connection_failure", "commit_then_timeout", "rate_limit"},
                {
                    "operation": "execute_payment",
                    "fields": {
                        k: payload[k]
                        for k in ("payment_id", "amount_minor", "currency", "recipient", "command_version")
                    },
                    "state": "committed" if committed else "uncommitted",
                },
            )
            if (
                fault
                and not fault.get("fixture_mismatch")
                and fault["behavior"] in {"connection_failure", "rate_limit"}
            ):
                audit(
                    c,
                    "payment_provider",
                    scope,
                    "fault_hit",
                    fault | {"attempt_actual": attempt, "stage": "before_commit", "entry_id": None},
                )
        if fault and fault.get("fixture_mismatch"):
            return JSONResponse(
                status_code=409, content={"error": "fixture_mismatch", "fault_id": fault["fault_id"]}
            )
        if fault and fault["behavior"] == "connection_failure":
            return DropBeforeCommit()
        if fault and fault["behavior"] == "rate_limit":
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "retry_after_ms": fault["duration_ms"]},
                headers={"Retry-After": "0"},
            )
        with db.begin() as c:
            scope_exists(c, "payment_provider", scope)
            # Serializes idempotency decisions but deliberately does not enforce PUT approval/balance policy.
            lock_scope(c, scope, "provider")
            old = (
                c.execute(
                    text(
                        "SELECT * FROM payment_provider.ledger WHERE project_id=:p AND run_id=:r AND idempotency_key=:idempotency_key"
                    ),
                    scope.params | payload,
                )
                .mappings()
                .first()
            )
            if old:
                if old["request_hash"] != digest(payload):
                    raise HTTPException(409, "幂等键对应不同指令")
                audit(
                    c,
                    "payment_provider",
                    scope,
                    "idempotent_reuse",
                    {"entry_id": str(old["entry_id"]), "command_id": body.refund_command_id},
                )
                return dict(old)
            payment = (
                c.execute(
                    text(
                        "SELECT * FROM payment_provider.payments WHERE project_id=:p AND run_id=:r AND payment_id=:payment_id"
                    ),
                    scope.params | payload,
                )
                .mappings()
                .first()
            )
            if not payment:
                raise HTTPException(404, "支付不存在")
            if payment["currency"] != body.currency:
                raise HTTPException(409, "支付币种不一致")
            entry_id, event_id = uuid4(), uuid4()
            processing = scope.model_dump(mode="json") | {
                "event_id": str(uuid4()),
                "entry_id": str(entry_id),
                "refund_command_id": body.refund_command_id,
                "payment_id": body.payment_id,
                "amount_minor": body.amount_minor,
                "currency": body.currency,
                "status": "execution_pending",
                "state_version": 1,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            audit(
                c,
                "payment_provider",
                scope,
                "processing_event_created",
                {"command_id": body.refund_command_id, "callback": processing},
            )
            row = (
                c.execute(
                    text("""INSERT INTO payment_provider.ledger
              (project_id,run_id,entry_id,idempotency_key,refund_command_id,payment_id,amount_minor,currency,recipient,request_hash,status,command_version,approval)
              VALUES (:p,:r,:entry_id,:idempotency_key,:refund_command_id,:payment_id,:amount_minor,:currency,:recipient,:h,'succeeded',:command_version,CAST(:approval AS jsonb)) RETURNING *"""),
                    scope.params
                    | payload
                    | {
                        "entry_id": entry_id,
                        "h": digest(payload),
                        "approval": canonical(payload["approval"]),
                    },
                )
                .mappings()
                .one()
            )
            callback = scope.model_dump(mode="json") | {
                "event_id": str(event_id),
                "entry_id": str(entry_id),
                "refund_command_id": body.refund_command_id,
                "payment_id": body.payment_id,
                "amount_minor": body.amount_minor,
                "currency": body.currency,
                "status": "succeeded",
                "state_version": 2,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            c.execute(
                text(
                    "INSERT INTO payment_provider.outbox (project_id,run_id,event_id,entry_id,payload) VALUES (:p,:r,:e,:entry,CAST(:payload AS jsonb))"
                ),
                scope.params | {"e": event_id, "entry": entry_id, "payload": canonical(callback)},
            )
            audit(
                c,
                "payment_provider",
                scope,
                "execution_committed",
                {"entry_id": str(entry_id), "command_id": body.refund_command_id, "attempt": attempt},
            )
            if fault and fault["behavior"] == "commit_then_timeout":
                audit(
                    c,
                    "payment_provider",
                    scope,
                    "fault_hit",
                    fault
                    | {
                        "attempt_actual": attempt,
                        "stage": "after_commit_response_withheld",
                        "entry_id": str(entry_id),
                    },
                )
        # Exiting db.begin committed both money and fault evidence before withholding bytes.
        if fault and fault["behavior"] == "commit_then_timeout":
            return LoseCommittedResponse()
        return dict(row)

    @app.get("/executions/{idempotency_key}")
    def query(idempotency_key: str, request: Request):
        scope, _ = authorize(request, "provider_execute")
        with db.connect() as c:
            row = (
                c.execute(
                    text(
                        "SELECT * FROM payment_provider.ledger WHERE project_id=:p AND run_id=:r AND idempotency_key=:k"
                    ),
                    scope.params | {"k": idempotency_key},
                )
                .mappings()
                .first()
            )
        if not row:
            raise HTTPException(404, "执行不存在")
        return dict(row)

    @app.post("/test/deliver")
    def deliver(request: Request, body: Delivery | None = None):
        delivery = body or Delivery()
        test_only()
        scope, _ = authorize(request, "provider_admin")
        sent = 0
        with db.begin() as c:
            lock_scope(c, scope, "provider")
            snapshot = c.execute(
                text("SELECT snapshot FROM payment_provider.namespaces WHERE project_id=:p AND run_id=:r"),
                scope.params,
            ).scalar()
            if snapshot is None:
                raise HTTPException(404, "命名空间不存在")
            put_origin = c.execute(
                text("SELECT put_origin FROM payment_provider.namespaces WHERE project_id=:p AND run_id=:r"),
                scope.params,
            ).scalar_one()
            rows = (
                c.execute(
                    text(
                        "SELECT * FROM payment_provider.outbox WHERE project_id=:p AND run_id=:r ORDER BY event_id FOR UPDATE"
                    ),
                    scope.params,
                )
                .mappings()
                .all()
            )
            for row in rows:
                if delivery.command_id and row["payload"]["refund_command_id"] != delivery.command_id:
                    continue
                body = canonical(row["payload"]).encode()
                stamp = int(time.time())
                signed = {
                    "X-Webhook-Timestamp": str(stamp),
                    "X-Webhook-Signature": signature(scope, stamp, body),
                }
                for column, origin, path in [
                    (
                        "put_delivered",
                        put_origin,
                        "/callbacks",
                    ),
                    (
                        "platform_delivered",
                        os.environ.get("EXAMPLE_API_ORIGIN", "http://127.0.0.1:8000"),
                        "/api/webhooks/" + snapshot["binding_id"],
                    ),
                ]:
                    if row[column]:
                        continue
                    try:
                        result = SafeHTTP().request("POST", origin, path, headers=signed, body=body)
                    except BoundaryError:
                        result = {"status": 503}
                    c.execute(
                        text(
                            f"UPDATE payment_provider.outbox SET attempts=attempts+1,{column}=:ok WHERE project_id=:p AND run_id=:r AND event_id=:e"
                        ),
                        scope.params | {"ok": result["status"] == 200, "e": row["event_id"]},
                    )
                    audit(
                        c,
                        "payment_provider",
                        scope,
                        "callback_delivery",
                        {
                            "receiver": column,
                            "event_id": str(row["event_id"]),
                            "command_id": row["payload"]["refund_command_id"],
                            "status": row["payload"]["status"],
                            "state_version": 2,
                            "response": result,
                        },
                    )
                    if result["status"] == 200:
                        sent += 1
        if delivery.behavior != "normal":
            with db.begin() as c:
                candidates = [x for x in rows if x["payload"]["refund_command_id"] == delivery.command_id]
                if not candidates:
                    raise HTTPException(409, "没有可投递的独立执行")
                row = candidates[0]
                fault = match_fault(
                    c,
                    "payment_provider",
                    scope,
                    delivery.command_id,
                    1,
                    {delivery.behavior},
                    {
                        "operation": "deliver_callback",
                        "state": "committed",
                        "fields": {
                            k: row["payload"].get(k) for k in ("payment_id", "amount_minor", "currency")
                        },
                    },
                )
                if not fault:
                    raise HTTPException(409, "故障计划不存在")
                if fault.get("fixture_mismatch"):
                    return JSONResponse(status_code=409, content={"error": "fixture_mismatch"})
                value = dict(row["payload"])
                if delivery.behavior == "webhook_reorder":
                    value = c.execute(
                        text(
                            "SELECT payload->'callback' FROM payment_provider.audit WHERE project_id=:p AND run_id=:r AND kind='processing_event_created' AND payload->'callback'->>'entry_id'=:entry ORDER BY sequence LIMIT 1"
                        ),
                        scope.params | {"entry": str(row["entry_id"])},
                    ).scalar_one()
                    if not value:
                        raise HTTPException(409, "缺少提交前已保存的旧回调")
                audit(
                    c,
                    "payment_provider",
                    scope,
                    "fault_hit",
                    fault | {"stage": "callback_delivery", "entry_id": str(row["entry_id"])},
                )
            raw = canonical(value).encode()
            stamp = int(time.time())
            signed = {"X-Webhook-Timestamp": str(stamp), "X-Webhook-Signature": signature(scope, stamp, raw)}
            for receiver, origin, path in [
                ("put", put_origin, "/callbacks"),
                (
                    "platform",
                    os.environ.get("EXAMPLE_API_ORIGIN", "http://127.0.0.1:8000"),
                    "/api/webhooks/" + snapshot["binding_id"],
                ),
            ]:
                started = time.time()
                result = SafeHTTP().request("POST", origin, path, headers=signed, body=raw)
                with db.begin() as c:
                    audit(
                        c,
                        "payment_provider",
                        scope,
                        "callback_delivery",
                        {
                            "receiver": receiver,
                            "event_id": value["event_id"],
                            "command_id": delivery.command_id,
                            "status": value["status"],
                            "state_version": value.get("state_version", 2),
                            "response": result,
                            "started_at": started,
                            "ended_at": time.time(),
                            "fault_id": fault["fault_id"],
                        },
                    )
                sent += result["status"] == 200
        return {"delivered": sent}

    return app


app = create_app()
