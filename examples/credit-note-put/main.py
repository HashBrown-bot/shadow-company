"""Independent credit-note product: JSON-RPC, document persistence and independent payment service.

No imports from the original PUT, simulator or evaluator. This example supports serial
approval/refund flows only; it does not advertise fault or barrier/replay capabilities.
"""

import json
import os
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import Field, ValidationError
from sqlalchemy import text

from packages.contracts.config import Model
from packages.transport.example import Callback, Refund, Seed, install_errors, lock_scope
from packages.transport.http import SafeHTTP
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

PROVIDER = "http://127.0.0.1:8002"
FIELDS = {
    "noteNumber": "refund_id",
    "chargeReference": "payment_id",
    "units": "amount_minor",
    "unitCurrency": "currency",
    "payee": "recipient",
    "revision": "version",
    "phase": "status",
    "authorization": "approval",
    "settlementReference": "provider_entry_id",
}


def rename(value, mapping):
    if isinstance(value, dict):
        return {mapping.get(k, k): rename(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [rename(v, mapping) for v in value]
    return value


def snapshot(note):
    return {k: note[k] for k in ("refund_id", "amount_minor", "currency", "recipient", "version")}


class RPC(Model):
    jsonrpc: Literal["2.0"]
    id: str = Field(min_length=1, max_length=64)
    method: Literal[
        "system.describe",
        "identity.describe",
        "sandbox.initialize",
        "sandbox.purge",
        "sandbox.version",
        "notes.issue",
        "notes.fetch",
        "notes.authorize",
        "notes.revise",
        "notes.settle",
        "notes.cancel",
    ]
    params: dict


def create_app(engine=None):
    db = engine if engine is not None else make_engine()
    app = FastAPI(title="Independent credit note example")
    install_errors(app)

    def read(c, scope, number):
        row = c.execute(
            text("SELECT document FROM credit_note.notes WHERE project_id=:p AND run_id=:r AND note_id=:n"),
            scope.params | {"n": number},
        ).scalar()
        if row is None:
            raise HTTPException(404, "贷项单不存在")
        return row

    def save(c, scope, note):
        c.execute(
            text("""INSERT INTO credit_note.notes VALUES (:p,:r,:n,CAST(:d AS jsonb))
          ON CONFLICT(project_id,run_id,note_id) DO UPDATE SET document=EXCLUDED.document"""),
            scope.params | {"n": note["refund_id"], "d": canonical(note)},
        )

    @app.get("/health")
    def health():
        with db.connect() as c:
            c.execute(text("SELECT 1 FROM credit_note.notes LIMIT 0"))
        return {"status": "ok", "example": True, "service": "credit-note-put"}

    def perform(message, request):
        method, params = message.method, message.params
        roles = (
            ("put_admin",)
            if method.startswith("sandbox.")
            else ("approver",)
            if method == "notes.authorize"
            else ("support", "approver", "customer_a", "customer_b")
            if method in {"identity.describe", "notes.fetch", "system.describe"}
            else ("support",)
        )
        scope, role = authorize(request, *roles)
        if method.startswith("sandbox."):
            test_only()
        if method == "system.describe":
            return 200, {
                "example": True,
                "adapter": "rpc_credit_v1",
                "supported_versions": ["fixed", "buggy"],
                "wire": "POST /rpc JSON-RPC 2.0",
                "normalization": "canonical_refund_observation_v1",
                "actions": {
                    "request_refund": {
                        "method": "POST",
                        "path": "/refunds",
                        "semantic": "create_application",
                    },
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
                    "read_refund": {
                        "method": "GET",
                        "path": "/refunds/{refund_id}",
                        "semantic": "observe_application",
                    },
                },
                "provider_origin": PROVIDER,
                "reset_path": "/test/reset",
                "clock_support": ["realtime", "event_compressed"],
                "approval_threshold_minor": 200000,
                "threshold_operator": "gt",
                "partial_refunds_allowed": True,
                "test_mode": os.environ.get("EXAMPLE_TEST_MODE") == "1",
                "supported_scenarios": [f"S{i:02}" for i in range(1, 11)],
            }
        if method == "identity.describe":
            return 200, scope.model_dump(mode="json") | {
                "identity_id": role,
                "role": role,
                "permissions": {
                    "support": ["request_refund", "execute_refund", "read_refund", "amend_refund"],
                    "approver": ["approve_refund", "read_refund"],
                    "customer_a": ["read_own_refund"],
                    "customer_b": ["read_own_refund"],
                }[role],
            }
        with db.begin() as c:
            lock_scope(c, scope, "credit-note")
            namespace = (
                c.execute(
                    text(
                        "SELECT snapshot,variant FROM credit_note.namespaces WHERE project_id=:p AND run_id=:r"
                    ),
                    scope.params,
                )
                .mappings()
                .first()
            )
            if method == "sandbox.initialize":
                seed = Seed.model_validate(rename(params, FIELDS)).model_dump(mode="json")
                if namespace and namespace["snapshot"] != seed:
                    raise HTTPException(409, "初始化快照冲突")
                if not namespace:
                    c.execute(
                        text(
                            "INSERT INTO credit_note.namespaces(project_id,run_id,snapshot) VALUES (:p,:r,CAST(:s AS jsonb))"
                        ),
                        scope.params | {"s": canonical(seed)},
                    )
                return 200, {"snapshot_hash": digest(seed)}
            if method == "sandbox.purge":
                counts = {}
                for table in ("receipts", "notes", "namespaces"):
                    counts[table] = c.execute(
                        text(f"DELETE FROM credit_note.{table} WHERE project_id=:p AND run_id=:r"),
                        scope.params,
                    ).rowcount
                return 200, {"reset": True, "removed": counts}
            if not namespace:
                raise HTTPException(404, "命名空间不存在")
            if method == "sandbox.version":
                if params.get("variant") not in {"fixed", "buggy"}:
                    raise HTTPException(422, "未知版本")
                if c.execute(
                    text("SELECT 1 FROM credit_note.notes WHERE project_id=:p AND run_id=:r LIMIT 1"),
                    scope.params,
                ).scalar():
                    raise HTTPException(409, "已有业务，不能切换版本")
                c.execute(
                    text("UPDATE credit_note.namespaces SET variant=:v WHERE project_id=:p AND run_id=:r"),
                    scope.params | {"v": params["variant"]},
                )
                return 200, {"configured": True}
            number = params.get("noteNumber")
            values = rename(params, FIELDS)
            if method == "notes.issue":
                values["refund_command_id"] = values.pop("refund_id", None)
                refund = Refund.model_validate(values)
                payment = next(
                    (p for p in namespace["snapshot"]["payments"] if p["payment_id"] == refund.payment_id),
                    None,
                )
                if not payment:
                    raise HTTPException(404, "原支付不存在")
                if payment["currency"] != refund.currency:
                    raise HTTPException(409, "币种冲突")
                existing = c.execute(
                    text(
                        "SELECT document FROM credit_note.notes WHERE project_id=:p AND run_id=:r AND note_id=:n"
                    ),
                    scope.params | {"n": number},
                ).scalar()
                if existing:
                    if any(
                        existing[k] != getattr(refund, k)
                        for k in ("payment_id", "amount_minor", "currency", "recipient")
                    ):
                        raise HTTPException(409, "指令参数冲突")
                    return 201, existing
                note = (
                    refund.model_dump(exclude={"refund_command_id"})
                    | scope.model_dump(mode="json")
                    | {
                        "refund_id": number,
                        "version": 1,
                        "status": "approval_pending" if refund.amount_minor > 200000 else "requested",
                        "approval": None,
                        "provider_entry_id": None,
                        "owner_id": "customer_a",
                        "created_by": role,
                    }
                )
                save(c, scope, note)
                return 201, note
            note = read(c, scope, number)
            if method == "notes.fetch":
                if role.startswith("customer_") and note["owner_id"] != role:
                    raise HTTPException(403, "无权读取他人贷项单")
                return 200, note
            if method == "notes.authorize":
                note["approval"] = snapshot(note) | {
                    "approved_by": role,
                    "approved": True,
                    "approval_id": str(uuid4()),
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                }
                note["status"] = "approved"
            elif method == "notes.revise":
                amount = params.get("units")
                if type(amount) is not int or not 0 < amount <= 10**12 or note["status"] == "succeeded":
                    raise HTTPException(409, "金额或状态不可修改")
                note.update(
                    amount_minor=amount,
                    version=note["version"] + 1,
                    status="approval_pending" if amount > 200000 else "requested",
                )
                if namespace["variant"] == "fixed":
                    note["approval"] = None
            elif method == "notes.cancel":
                if note["status"] != "succeeded":
                    note["status"] = "cancelled"
            elif method == "notes.settle":
                if note["status"] in {"succeeded", "cancelled"}:
                    return 200, note
                if note["amount_minor"] > 200000 and (
                    not note["approval"]
                    or (
                        namespace["variant"] == "fixed"
                        and any(note["approval"].get(k) != v for k, v in snapshot(note).items())
                    )
                ):
                    raise HTTPException(409, "需要当前修订版本的授权")
                all_notes = (
                    c.execute(
                        text("SELECT document FROM credit_note.notes WHERE project_id=:p AND run_id=:r"),
                        scope.params,
                    )
                    .scalars()
                    .all()
                )
                spent = sum(
                    n["amount_minor"]
                    for n in all_notes
                    if n["status"] == "succeeded"
                    and n["payment_id"] == note["payment_id"]
                    and n["currency"] == note["currency"]
                )
                payment = next(
                    p for p in namespace["snapshot"]["payments"] if p["payment_id"] == note["payment_id"]
                )
                if spent + note["amount_minor"] > payment["amount_minor"]:
                    raise HTTPException(409, "贷项单累计超过原支付")
                transfer = {
                    k: note[k] for k in ("payment_id", "amount_minor", "currency", "recipient", "approval")
                } | {
                    "refund_command_id": number,
                    "idempotency_key": "credit-" + number,
                    "command_version": note["version"],
                }
                result = SafeHTTP().request(
                    "POST", PROVIDER, "/executions", headers=headers("provider_execute", scope), body=transfer
                )
                if result["status"] != 200:
                    raise HTTPException(503, "支付依赖未确认执行")
                note.update(status="succeeded", provider_entry_id=result["body"]["entry_id"])
            save(c, scope, note)
            return 200, note

    @app.post("/rpc")
    def rpc(message: RPC, request: Request):
        try:
            code, document = perform(message, request)
        except HTTPException as error:
            code, document = error.status_code, {"error": str(error.detail)}
        except ValidationError:
            code, document = 422, {"error": "RPC 参数无效"}
        return {
            "jsonrpc": "2.0",
            "id": message.id,
            "result": {"code": code, "document": rename(document, {v: k for k, v in FIELDS.items()})},
        }

    @app.post("/callbacks")
    async def callback(request: Request):
        raw = await request.body()
        if len(raw) > 65536:
            raise HTTPException(413, "回调过大")
        try:
            event = Callback.model_validate_json(raw)
        except ValueError:
            raise HTTPException(422, "回调格式无效") from None
        scope = Scope(project_id=event.project_id, run_id=event.run_id)
        verify_signature(
            scope, request.headers.get("X-Webhook-Timestamp"), raw, request.headers.get("X-Webhook-Signature")
        )
        with db.begin() as c:
            lock_scope(c, scope, "credit-note")
            note = read(c, scope, event.refund_command_id)
            if (
                str(note["provider_entry_id"]) != str(event.entry_id)
                or any(note[k] != getattr(event, k) for k in ("amount_minor", "payment_id", "currency"))
                or event.status != "succeeded"
            ):
                raise HTTPException(409, "回调与支付结果冲突")
            old = c.execute(
                text(
                    "SELECT digest FROM credit_note.receipts WHERE project_id=:p AND run_id=:r AND event_id=:e"
                ),
                scope.params | {"e": event.event_id},
            ).scalar()
            hash_ = digest(json.loads(raw))
            if old and old != hash_:
                raise HTTPException(409, "重复事件内容冲突")
            if not old:
                c.execute(
                    text("INSERT INTO credit_note.receipts VALUES (:p,:r,:e,:h)"),
                    scope.params | {"e": event.event_id, "h": hash_},
                )
        return {"accepted": True, "duplicate": old is not None}

    return app


app = create_app()
