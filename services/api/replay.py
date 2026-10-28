"""Explicit replay modes and source-preserving target contract selection."""

from copy import deepcopy
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from adapters.http.registry import validate_example
from packages.contracts.replay import ReplayInput
from packages.simulator.e3 import contract, new_run
from packages.simulator.replay import bundle, check_assets, freeze, history
from packages.transport.http import BoundaryError
from packages.transport.security import Scope, digest


def router(db):
    api = APIRouter()

    @api.get("/api/runs/{run_id}/history")
    def get_history(run_id: UUID, project_id: UUID):
        return history(db, Scope(project_id=project_id, run_id=run_id))

    @api.get("/api/runs/{run_id}/manifest")
    def manifest(run_id: UUID, project_id: UUID):
        _, row, seal, assets, _ = bundle(db, Scope(project_id=project_id, run_id=run_id))
        return {
            "planned": row,
            "completion": seal,
            "assets": assets,
            "integrity_issues": check_assets(row["payload"], assets),
        }

    @api.post("/api/runs/{run_id}/replay")
    def replay(run_id: UUID, body: ReplayInput):
        source = Scope(project_id=body.project_id, run_id=run_id)
        if body.mode == "history":
            return history(db, source)
        scope = Scope(project_id=body.project_id, run_id=uuid4())
        request_data = body.model_dump(mode="json") | {"source_run_id": str(run_id)}
        config, hash_ = contract(db, body.project_id, body.target_contract_version)
        if config.product.adapter == "rpc_credit_v1":
            raise HTTPException(422, "第二示例尚未声明 E6 受控重放能力")
        if config.product.version != body.target_product_version:
            raise HTTPException(422, "目标 PUT 版本必须与所选不可变契约一致")
        try:
            validate_example(config)
        except BoundaryError as error:
            raise HTTPException(422, str(error)) from None
        with db.begin() as c:
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"),
                {"k": str(body.project_id) + ":" + body.idempotency_key},
            )
            old = (
                c.execute(
                    text(
                        "SELECT run_id,request_hash FROM run_inputs WHERE project_id=:p AND request_key=:key"
                    ),
                    {"p": body.project_id, "key": body.idempotency_key},
                )
                .mappings()
                .first()
            )
            if old:
                if old["request_hash"] != digest(request_data):
                    raise HTTPException(409, "请求幂等键对应不同重放输入")
                return {"project_id": str(body.project_id), "run_id": str(old["run_id"]), "reused": True}
            _, source_manifest, source_seal, assets, data = bundle(db, source, require_seal=True)
            if (
                check_assets(source_manifest["payload"], assets)
                or digest(source_manifest["payload"]) != source_manifest["content_hash"]
                or digest(source_seal["payload"]) != source_seal["content_hash"]
            ):
                raise HTTPException(409, "fixture_mismatch: 源资产缺失或内容哈希不一致，不能生成通过结论")
            if body.mode == "controlled":
                semantics = config.model_dump(mode="json")
                semantics["product"].pop("version")
                if digest(semantics) != source_manifest["payload"]["contract_semantics_hash"]:
                    raise HTTPException(
                        422,
                        "controlled 仅支持同一已审阅的环境、规则、预算与控制契约；条件变化请用 input 并查看不可比较项",
                    )
            active = c.execute(
                text(
                    "SELECT passed FROM preflights WHERE project_id=:p AND contract_hash=:h ORDER BY created_at DESC LIMIT 1"
                ),
                {"p": body.project_id, "h": hash_},
            ).scalar()
            if active is not True:
                raise HTTPException(409, "目标契约尚未通过接入预检")
            plan = deepcopy(data["plan"])
            if (
                digest({"payments": plan["payments"]}) != assets["snapshot"]["content_hash"]
                or digest(plan["faults"]) != assets["faults"]["content_hash"]
            ):
                raise HTTPException(409, "fixture_mismatch: 源计划与快照/故障资产不一致")
            actors = (
                [f.model_dump(mode="json") for f in body.actor_fixtures]
                if body.actor_fixtures is not None
                else assets["actors"]["payload"]
            )
            payload = {"kind": "e6_replay", "request": request_data, "plan": plan}
            # Scenario selection is inherited from frozen input, not re-generated from the target code.
            payload["request"] = request_data | {"scenarios": data["request"]["scenarios"]}
            actor_policy = None
            if source_manifest["payload"].get("actor_policy"):
                from packages.simulator.actors import load_policy

                actor_policy = load_policy(db, source)
                payload["request"]["actor_policy"] = actor_policy.model_dump(mode="json")
            binding = new_run(
                c, scope, body.target_contract_version, config, payload, request_hash=digest(request_data)
            )
            freeze(
                c,
                scope,
                config,
                plan,
                binding,
                body.target_contract_version,
                replay={
                    "mode": body.mode,
                    "source_run_id": str(run_id),
                    "source_manifest_hash": source_manifest["content_hash"],
                    "source_seal_hash": source_seal["content_hash"],
                    "purpose": "replay",
                },
                actors=actors,
                actor_policy=actor_policy,
            )
            c.execute(
                text("INSERT INTO jobs(project_id,run_id,job_id,idempotency_key) VALUES (:p,:r,:id,:key)"),
                scope.params | {"id": uuid4(), "key": body.idempotency_key},
            )
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=202,
            content={
                **scope.model_dump(mode="json"),
                "status": "queued",
                "verdict": "inconclusive",
                "mode": body.mode,
                "reuse_product_outputs": False,
            },
        )

    @api.get("/api/runs/{run_id}/compare")
    def compare(run_id: UUID, other_run_id: UUID, project_id: UUID, format: str = "json"):
        from packages.evaluators.comparison import compare_runs, render_compare

        if format not in {"json", "html"}:
            raise HTTPException(422, "format 仅支持 json/html")
        result = compare_runs(
            db, Scope(project_id=project_id, run_id=run_id), Scope(project_id=project_id, run_id=other_run_id)
        )
        if format == "html":
            return HTMLResponse(
                render_compare(result),
                headers={
                    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
                },
            )
        return result

    return api
