"""Shared wire types and plumbing, with no shared business ledger or expected answers."""

from typing import Annotated
from uuid import UUID

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, Field, StrictInt
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from packages.contracts.config import Currency, Identifier, Model, safe_validation_errors
from packages.transport.security import Scope

Minor = Annotated[StrictInt, Field(gt=0, le=10**12)]


class Payment(Model):
    payment_id: Identifier
    amount_minor: Minor
    currency: Currency


class Seed(Model):
    payments: Annotated[list[Payment], Field(min_length=1, max_length=50)]
    binding_id: UUID


class Refund(Model):
    refund_command_id: Identifier
    payment_id: Identifier
    amount_minor: Minor
    currency: Currency
    recipient: Identifier


class Execute(Refund):
    idempotency_key: Identifier
    command_version: Annotated[StrictInt, Field(gt=0)] | None = None
    approval: dict | None = None


class Callback(Scope):
    event_id: UUID
    entry_id: UUID
    refund_command_id: Identifier
    payment_id: Identifier
    amount_minor: Minor
    currency: Currency
    status: str
    state_version: Annotated[StrictInt, Field(ge=1, le=2)] = 2
    occurred_at: AwareDatetime | None = None


def install_errors(app: FastAPI):
    @app.exception_handler(RequestValidationError)
    async def validation(request, error):
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "validation_error", "details": safe_validation_errors(error.errors())}
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request, error):
        return JSONResponse(status_code=503, content={"error": {"code": "database_unavailable"}})


def scope_exists(conn, schema, scope):
    from fastapi import HTTPException

    if not conn.execute(
        text(f"SELECT 1 FROM {schema}.namespaces WHERE project_id=:p AND run_id=:r"), scope.params
    ).scalar():
        raise HTTPException(404, "命名空间不存在")


def lock_scope(conn, scope, service):
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope,0))"),
        {"scope": service + ":" + scope.namespace},
    )
