"""Test-only wire controls; services persist exclusively in their own schema."""

import asyncio
from threading import Barrier, BrokenBarrierError, Lock
from typing import Annotated, Literal

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import Field, StrictInt
from sqlalchemy import text

from packages.contracts.config import Identifier, Model
from packages.transport.security import authorize, canonical, test_only


class SemanticMatch(Model):
    operation: Literal["execute_payment", "deliver_callback", "approve_snapshot"]
    fields: dict[Literal["payment_id", "amount_minor", "currency", "recipient", "command_version"], str | int]
    state: Literal["uncommitted", "committed", "approval_pending"]


class FaultPlan(Model):
    fault_id: Identifier
    behavior: Literal[
        "connection_failure",
        "commit_then_timeout",
        "webhook_duplicate",
        "webhook_reorder",
        "rate_limit",
        "approver_offline",
    ]
    command_id: Identifier
    semantic: SemanticMatch | None = None
    attempt: Annotated[StrictInt, Field(ge=1, le=10)]
    times: Annotated[StrictInt, Field(ge=1, le=10)]
    duration_ms: Annotated[StrictInt, Field(ge=0, le=5000)]


class BarrierPlan(Model):
    group_id: Identifier
    command_ids: list[Identifier] = Field(min_length=1, max_length=4)
    parties: Annotated[StrictInt, Field(ge=2, le=4)]


class Delivery(Model):
    command_id: Identifier | None = None
    behavior: Literal["normal", "webhook_duplicate", "webhook_reorder"] = "normal"


def audit(c, schema, scope, kind, payload):
    return c.execute(
        text(
            f"INSERT INTO {schema}.audit(project_id,run_id,kind,payload) VALUES (:p,:r,:k,CAST(:v AS jsonb)) RETURNING sequence"
        ),
        scope.params | {"k": kind, "v": canonical(payload)},
    ).scalar_one()


def match_fault(c, schema, scope, command, attempt, behaviors, semantics=None):
    plans = c.execute(
        text(f"SELECT payload FROM {schema}.fault_plans WHERE project_id=:p AND run_id=:r ORDER BY fault_id"),
        scope.params,
    ).scalars()
    for plan in plans:
        if plan["behavior"] not in behaviors or plan["command_id"] != command:
            continue
        hits = c.execute(
            text(
                f"SELECT count(*) FROM {schema}.audit WHERE project_id=:p AND run_id=:r AND kind='fault_hit' AND payload->>'fault_id'=:id"
            ),
            scope.params | {"id": plan["fault_id"]},
        ).scalar_one()
        if hits >= plan["times"]:
            continue
        if plan.get("semantic"):
            expected = plan["semantic"]
            matched = (
                semantics is not None
                and all(semantics.get(k) == expected[k] for k in ("operation", "state"))
                and all(semantics.get("fields", {}).get(k) == v for k, v in expected["fields"].items())
            )
            audit(
                c,
                schema,
                scope,
                "fixture_matched" if matched else "fixture_mismatch",
                {
                    "fault_id": plan["fault_id"],
                    "command_id": command,
                    "expected": expected,
                    "actual": semantics,
                },
            )
            if not matched:
                return {"fixture_mismatch": True, "fault_id": plan["fault_id"]}
            return plan
        if plan["attempt"] <= attempt < plan["attempt"] + plan["times"]:
            return plan
    return None


def install_controls(app, db, schema, role):
    @app.post("/test/faults")
    def configure(body: FaultPlan, request: Request):
        test_only()
        scope, _ = authorize(request, role)
        value = body.model_dump(exclude_none=True)
        with db.begin() as c:
            c.execute(
                text(
                    f"INSERT INTO {schema}.fault_plans VALUES (:p,:r,:id,CAST(:v AS jsonb)) ON CONFLICT DO NOTHING"
                ),
                scope.params | {"id": body.fault_id, "v": canonical(value)},
            )
            old = c.execute(
                text(
                    f"SELECT payload FROM {schema}.fault_plans WHERE project_id=:p AND run_id=:r AND fault_id=:id"
                ),
                scope.params | {"id": body.fault_id},
            ).scalar_one()
            if old != value:
                raise HTTPException(409, "不可覆盖故障计划")
        return {"configured": True, "plan": value}

    @app.get("/test/evidence")
    def evidence(request: Request):
        test_only()
        scope, _ = authorize(request, role, *(["provider_reader"] if schema == "payment_provider" else []))
        with db.connect() as c:
            plans = (
                c.execute(
                    text(
                        f"SELECT payload FROM {schema}.fault_plans WHERE project_id=:p AND run_id=:r ORDER BY fault_id"
                    ),
                    scope.params,
                )
                .scalars()
                .all()
            )
            rows = (
                c.execute(
                    text(f"SELECT * FROM {schema}.audit WHERE project_id=:p AND run_id=:r ORDER BY sequence"),
                    scope.params,
                )
                .mappings()
                .all()
            )
        return scope.model_dump(mode="json") | {"plans": plans, "records": [dict(x) for x in rows]}


class DropBeforeCommit(Response):
    """Real truncated HTTP connection, before any ledger write. Not a caller exception."""

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"1")]})
        # Uvicorn closes the transport for incomplete Content-Length. Client sees IncompleteRead.
        await send({"type": "http.response.body", "body": b"", "more_body": False})


class LoseCommittedResponse(Response):
    """Withhold all headers until the real client read timeout disconnects."""

    async def __call__(self, scope, receive, send):
        async def disconnected():
            while (await receive())["type"] != "http.disconnect":
                pass

        try:
            await asyncio.wait_for(disconnected(), timeout=5)
        except TimeoutError:
            await Response(status_code=504)(scope, receive, send)


class EntryBarriers:
    def __init__(self, db):
        self.db = db
        self.lock = Lock()
        self.groups = {}

    def configure(self, scope, plan):
        key = (scope.namespace, plan.group_id)
        with self.lock:
            if key not in self.groups:
                self.groups[key] = (plan, Barrier(plan.parties), Barrier(plan.parties))
        with self.db.begin() as c:
            audit(c, "refund_put", scope, "barrier_plan", plan.model_dump())

    def wait(self, scope, group, command, phase="entry"):
        if not group:
            return
        with self.lock:
            item = self.groups.get((scope.namespace, group))
        if not item or command not in item[0].command_ids:
            raise HTTPException(409, "并发组未配置或对象不匹配")
        with self.db.begin() as c:
            audit(
                c,
                "refund_put",
                scope,
                "barrier_arrived",
                {"group_id": group, "command_id": command, "phase": phase},
            )
        try:
            item[1 if phase == "entry" else 2].wait(timeout=4)
        except BrokenBarrierError:
            raise HTTPException(503, "barrier 未集齐") from None
        with self.db.begin() as c:
            audit(
                c,
                "refund_put",
                scope,
                "barrier_released",
                {"group_id": group, "command_id": command, "phase": phase},
            )
