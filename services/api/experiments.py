"""E7 paired runs on a real PUT. Ordinary APIs use rule actors in both arms."""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from packages.contracts.actors import ActorPolicy, ExperimentInput, FindingReview
from packages.contracts.config import Configuration
from packages.simulator.e3 import contract, preflight
from packages.transport.http import BoundaryError
from packages.transport.security import Scope, canonical, digest


def router(db, enqueue):
    api = APIRouter()

    @api.get("/api/actors/schema")
    def schemas():
        from packages.contracts.actors import ACTION_SCHEMA

        return {
            "policy": ActorPolicy.model_json_schema(),
            "action": ACTION_SCHEMA.json_schema(),
            "live_service": "not_installed_or_authorized",
            "default": ActorPolicy().model_dump(),
        }

    @api.post("/api/experiments", status_code=202)
    def experiment(body: ExperimentInput):
        from services.api.e3 import RunInput

        config, original_hash = contract(db, body.project_id, body.contract_version)
        request = body.model_dump(mode="json")
        with db.begin() as c:
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"),
                {"k": str(body.project_id) + ":experiment:" + body.idempotency_key},
            )
            old = (
                c.execute(
                    text("SELECT * FROM experiments WHERE project_id=:p AND request_key=:k"),
                    {"p": body.project_id, "k": body.idempotency_key},
                )
                .mappings()
                .first()
            )
            if old and old["content_hash"] != digest(request):
                raise HTTPException(409, "实验幂等键对应不同配置")
            experiment_id = old["experiment_id"] if old else uuid4()
            if not old:
                active = c.execute(
                    text(
                        "SELECT passed FROM preflights WHERE project_id=:p AND contract_hash=:h ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"p": body.project_id, "h": original_hash},
                ).scalar()
                if active is not True:
                    raise HTTPException(409, "原始契约需先通过预检")
                c.execute(
                    text("INSERT INTO experiments VALUES (:p,:e,:k,:h,CAST(:v AS jsonb))"),
                    {
                        "p": body.project_id,
                        "e": experiment_id,
                        "k": body.idempotency_key,
                        "h": digest(request),
                        "v": canonical(request),
                    },
                )
        runs = []
        for seed in body.seeds:
            data = config.model_dump(mode="json")
            data["runtime"]["seed"] = seed
            paired = Configuration.model_validate(data)
            version = "e7-" + paired.content_hash()[:40]
            with db.begin() as c:
                c.execute(
                    text("""INSERT INTO contracts(project_id,version,schema_version,content_hash,config)
                    VALUES (:p,:v,'0.2',:h,CAST(:config AS jsonb)) ON CONFLICT DO NOTHING"""),
                    {
                        "p": body.project_id,
                        "v": version,
                        "h": paired.content_hash(),
                        "config": paired.canonical_json(),
                    },
                )
                existing = c.execute(
                    text("SELECT content_hash FROM contracts WHERE project_id=:p AND version=:v"),
                    {"p": body.project_id, "v": version},
                ).scalar_one()
                if existing != paired.content_hash():
                    raise HTTPException(409, "配对契约版本冲突")
                active = c.execute(
                    text(
                        "SELECT passed FROM preflights WHERE project_id=:p AND contract_hash=:h ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"p": body.project_id, "h": paired.content_hash()},
                ).scalar()
            if active is not True:
                try:
                    verified = preflight(db, body.project_id, version)
                except BoundaryError:
                    raise HTTPException(409, "配对契约预检失败，实验未完成") from None
                if not verified["passed"]:
                    raise HTTPException(409, "配对契约预检失败，实验未完成")
            for mode in ("rule", "hybrid"):
                policy = ActorPolicy(mode=mode, budget=body.model_budget)
                run = enqueue(
                    RunInput(
                        project_id=body.project_id,
                        contract_version=version,
                        idempotency_key="experiment-" + digest([str(experiment_id), seed, mode]),
                        suite_scope="e7_core_20",
                        scenarios=body.scenarios,
                        actor_policy=policy,
                    )
                )
                with db.begin() as c:
                    c.execute(
                        text("INSERT INTO experiment_runs VALUES (:p,:r,:e,:s,:m) ON CONFLICT DO NOTHING"),
                        {"p": body.project_id, "r": run["run_id"], "e": experiment_id, "s": seed, "m": mode},
                    )
                runs.append({"run_id": run["run_id"], "seed": seed, "mode": mode})
        return {
            "project_id": str(body.project_id),
            "experiment_id": str(experiment_id),
            "runs": runs,
            "model_service_test": "not_run",
            "ai_increment_proven": False,
        }

    @api.get("/api/experiments/{experiment_id}")
    def get_experiment(experiment_id: UUID, project_id: UUID, format: str = "json"):
        from packages.evaluators.experiments import experiment_report, render_experiment

        if format not in {"json", "html"}:
            raise HTTPException(422, "format 仅支持 json/html")
        result = experiment_report(db, project_id, experiment_id)
        if format == "html":
            return HTMLResponse(
                render_experiment(result),
                headers={
                    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
                },
            )
        return result

    @api.post("/api/experiments/{experiment_id}/reviews", status_code=201)
    def review(experiment_id: UUID, body: FindingReview):
        from packages.evaluators.reporting import report

        scope = Scope(project_id=body.project_id, run_id=body.run_id)
        with db.connect() as c:
            member = c.execute(
                text("SELECT 1 FROM experiment_runs WHERE project_id=:p AND run_id=:r AND experiment_id=:e"),
                scope.params | {"e": experiment_id},
            ).scalar()
        if not member:
            raise HTTPException(404, "实验中没有该 run")
        result = report(db, scope)
        finding = next((f for f in result["findings"] if str(f["finding_id"]) == str(body.finding_id)), None)
        if not finding or finding["attribution"] != "product_defect" or not finding["evidence_refs"]:
            raise HTTPException(422, "仅可复核当前有证据的产品发现；不能把角色错误计为产品缺陷")
        payload = body.model_dump(mode="json") | {
            "evidence_hash": result["evidence_hash"],
            "experiment_id": str(experiment_id),
        }
        with db.begin() as c:
            c.execute(
                text("""INSERT INTO finding_reviews(project_id,run_id,review_id,finding_id,content_hash,payload)
              VALUES (:p,:r,:id,:f,:h,CAST(:v AS jsonb)) ON CONFLICT(project_id,run_id,finding_id) DO NOTHING"""),
                scope.params
                | {"id": uuid4(), "f": body.finding_id, "h": digest(payload), "v": canonical(payload)},
            )
            old = c.execute(
                text(
                    "SELECT content_hash FROM finding_reviews WHERE project_id=:p AND run_id=:r AND finding_id=:f"
                ),
                scope.params | {"f": body.finding_id},
            ).scalar_one()
            if old != digest(payload):
                raise HTTPException(409, "已有不可变人工复核，不能覆盖或在证据变化后复用")
        return {"saved": True, "content_hash": digest(payload)}

    return api
