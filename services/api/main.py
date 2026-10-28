"""Versioned contracts and local E3 execution API."""

from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, StringConstraints, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from packages.contracts.config import (
    ConfigSyntaxError,
    Configuration,
    Identifier,
    Model,
    parse_yaml,
    safe_validation_errors,
)
from packages.contracts.domain import Contract, Project
from packages.transport.access import access_request
from services.api.database import check_database, make_engine


class ProjectInput(Model):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    ownership: Annotated[str, Field(pattern="^local_team$")] = "local_team"
    local_access_policy: Annotated[str, Field(pattern="^loopback_only$")] = "loopback_only"


class ContractInput(Model):
    version: Identifier
    config: Configuration


class YamlInput(Model):
    yaml: str = Field(max_length=131072)


def create_app(engine=None):
    db = engine if engine is not None else make_engine()

    @asynccontextmanager
    async def lifespan(app):
        yield
        if engine is None:
            db.dispose()

    app = FastAPI(
        title="企业业务仿真平台 E9",
        version="0.6.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.db = db

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        try:
            await access_request(request)
            response = await call_next(request)
        except HTTPException as error:
            response = error_response(
                request,
                error.status_code,
                {401: "unauthorized", 403: "forbidden"}.get(error.status_code, "access_error"),
                str(error.detail),
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    def error_response(request, status, code, message, details=None):
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or [],
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response(
            request, 422, "validation_error", "请求配置无效", safe_validation_errors(error.errors())
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        codes = {
            404: "not_found",
            409: "version_conflict",
            501: "not_implemented",
            503: "database_unavailable",
        }
        return error_response(
            request, error.status_code, codes.get(error.status_code, "http_error"), str(error.detail)
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        return error_response(
            request, 503, "database_unavailable", "数据库不可用，请检查连接与迁移；未生成业务结论"
        )

    @app.get("/api/health")
    def health():
        try:
            revision = check_database(db)
        except (SQLAlchemyError, RuntimeError):
            raise HTTPException(503, "数据库不可用或迁移未完成") from None
        return {
            "status": "ok",
            "phase": "E9",
            "schema_version": "0.2",
            "database": "ready",
            "migration": revision,
            "business_execution": "e7_hybrid_offline",
        }

    @app.get("/api/contracts/schema")
    def schema():
        return Configuration.model_json_schema()

    @app.post("/api/contracts/validate")
    def validate(body: YamlInput, request: Request):
        try:
            config = parse_yaml(body.yaml)
        except ValidationError as error:
            return error_response(
                request, 422, "validation_error", "契约配置无效", safe_validation_errors(error.errors())
            )
        except ConfigSyntaxError as error:
            return error_response(request, 422, "yaml_error", str(error))
        return {
            "schema_version": config.schema_version,
            "content_hash": config.content_hash(),
            "valid": True,
            "preflight": "not_performed",
            "business_verdict": "inconclusive",
            "config": config.model_dump(mode="json"),
        }

    @app.post("/api/projects", status_code=201, response_model=Project)
    def create_project(body: ProjectInput):
        project = Project(**body.model_dump())
        with db.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (id,name,ownership,local_access_policy,created_at) VALUES (:id,:name,:ownership,:local_access_policy,:created_at)"
                ),
                project.model_dump(),
            )
        return project

    @app.get("/api/projects")
    def projects(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        granted = request.state.grant["projects"]
        where = "" if "*" in granted else " WHERE id::text = ANY(:granted)"
        with db.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT * FROM projects"
                        + where
                        + " ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"
                    ),
                    {"limit": limit, "offset": offset, "granted": granted},
                )
                .mappings()
                .all()
            )
            total = connection.execute(
                text("SELECT count(*) FROM projects" + where), {"granted": granted}
            ).scalar_one()
        from services.api.console import project_summary

        return {
            "items": [project_summary(db, r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.put("/api/projects/{project_id}/contract", response_model=Contract)
    def save_contract(project_id: UUID, body: ContractInput):
        contract = Contract(
            project_id=project_id,
            version=body.version,
            content_hash=body.config.content_hash(),
            config=body.config,
        )
        params = contract.model_dump(exclude={"config"}) | {"config": body.config.canonical_json()}
        with db.begin() as connection:
            if not connection.execute(
                text("SELECT 1 FROM projects WHERE id=:id"), {"id": project_id}
            ).scalar():
                raise HTTPException(404, "项目不存在")
            connection.execute(
                text("""INSERT INTO contracts (project_id,version,schema_version,content_hash,config,created_at)
                VALUES (:project_id,:version,:schema_version,:content_hash,CAST(:config AS jsonb),:created_at)
                ON CONFLICT (project_id,version) DO NOTHING"""),
                params,
            )
            existing = (
                connection.execute(
                    text("SELECT * FROM contracts WHERE project_id=:project_id AND version=:version"), params
                )
                .mappings()
                .one()
            )
            if existing["content_hash"] != contract.content_hash:
                raise HTTPException(409, "该契约版本已存在且内容不同；请保存为新版本，旧版本不可覆盖")
        return Contract(**existing)

    @app.get("/api/projects/{project_id}/contract/{version}", response_model=Contract)
    def get_contract(project_id: UUID, version: str):
        with db.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM contracts WHERE project_id=:project_id AND version=:version"),
                    {"project_id": project_id, "version": version},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise HTTPException(404, "项目或契约版本不存在")
        return Contract(**row)

    from services.api.e3 import router

    app.include_router(router(db))
    from services.api.replay import router as replay_router

    app.include_router(replay_router(db))

    from services.api.console import router as console_router

    app.include_router(console_router(db))
    from services.api.lifecycle import router as lifecycle_router

    app.include_router(lifecycle_router(db))
    return app


app = create_app()
