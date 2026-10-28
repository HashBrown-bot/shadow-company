"""Scoped local lifecycle. Remote deletion must succeed before platform evidence is purged."""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from packages.simulator.e3 import contract, reset_run
from packages.simulator.jobs import cancel
from packages.transport.http import BoundaryError
from packages.transport.security import Scope


def audit(c, project, operation, run=None, count=0):
    identifier = uuid4()
    c.execute(
        text("""INSERT INTO lifecycle_audits(audit_id,project_id,run_id,operation,record_count)
      VALUES (:id,:p,:r,:op,:count)"""),
        {"id": identifier, "p": project, "r": run, "op": operation, "count": count},
    )
    return str(identifier)


def stop_project(db, project, deleting=False):
    with db.begin() as c:
        row = c.execute(text("SELECT id FROM projects WHERE id=:p FOR UPDATE"), {"p": project}).first()
        if not row:
            raise HTTPException(404, "项目不存在")
        c.execute(
            text("UPDATE projects SET stopped=true,deleting=deleting OR :d WHERE id=:p"),
            {"p": project, "d": deleting},
        )
        runs = (
            c.execute(
                text("SELECT run_id FROM jobs WHERE project_id=:p AND state IN ('queued','leased')"),
                {"p": project},
            )
            .scalars()
            .all()
        )
        # Holding the project lock prevents all new_run paths (including replay/experiments).
        for run in runs:
            cancel(db, Scope(project_id=project, run_id=run))
        identifier = audit(c, project, "emergency_stop", count=len(runs))
    return {
        "stopped": True,
        "cancel_requested": len(runs),
        "audit_id": identifier,
        "inflight": "已派发动作保留后果；急停不撤回已执行支付",
    }


def delete_project(db, project):
    stop_project(db, project, deleting=True)
    with db.connect() as c:
        if c.execute(
            text("SELECT 1 FROM jobs WHERE project_id=:p AND state='leased' LIMIT 1"), {"p": project}
        ).scalar():
            raise HTTPException(409, "已急停；请等待在途 Worker 结束再重试删除")
        runs = (
            c.execute(text("SELECT run_id,contract_version FROM runs WHERE project_id=:p"), {"p": project})
            .mappings()
            .all()
        )
    for row in runs:
        config, _ = contract(db, project, row["contract_version"])
        try:
            reset_run(db, Scope(project_id=project, run_id=row["run_id"]), config)
        except BoundaryError:
            raise HTTPException(503, "远端清理未完成；保留平台证据，恢复服务后重试删除") from None
    with db.begin() as c:
        c.execute(text("SELECT id FROM projects WHERE id=:p FOR UPDATE"), {"p": project})
        identifier = audit(c, project, "delete_project", count=len(runs))
        c.execute(text("SELECT set_config('simulation.lifecycle_id',:id,true)"), {"id": identifier})
        # reset removed each run's evidence first. Remaining indexes and contracts cannot outlive a deleted project.
        for table in [
            "experiment_runs",
            "experiments",
            "preflights",
            "reset_audits",
            "run_inputs",
            "runs",
            "contracts",
        ]:
            c.execute(text(f"DELETE FROM {table} WHERE project_id=:p"), {"p": project})
        c.execute(text("DELETE FROM projects WHERE id=:p"), {"p": project})
    return {"deleted": True, "audit_id": identifier, "runs_removed": len(runs)}


def retain(db, project):
    with db.connect() as c:
        if not c.execute(text("SELECT 1 FROM projects WHERE id=:p"), {"p": project}).scalar():
            raise HTTPException(404, "项目不存在")
        runs = (
            c.execute(
                text("""SELECT r.run_id,r.contract_version,r.status,r.stop_reason,
          r.created_at + ((c.config->'artifacts'->>'trace_retention_days')::int * interval '1 day') <= clock_timestamp() AS expired
          FROM runs r JOIN contracts c ON c.project_id=r.project_id AND c.version=r.contract_version
          WHERE r.project_id=:p"""),
                {"p": project},
            )
            .mappings()
            .all()
        )
    raw, traces, deferred = 0, 0, []
    for row in runs:
        scope = Scope(project_id=project, run_id=row["run_id"])
        with db.begin() as c:
            count = c.execute(
                text(
                    "SELECT count(*) FROM private_evidence WHERE project_id=:p AND run_id=:r AND expires_at<=clock_timestamp()"
                ),
                scope.params,
            ).scalar_one()
            if count:
                identifier = audit(c, project, "expire_raw", scope.run_id, count)
                c.execute(text("SELECT set_config('simulation.lifecycle_id',:id,true)"), {"id": identifier})
                raw += c.execute(
                    text(
                        "DELETE FROM private_evidence WHERE project_id=:p AND run_id=:r AND expires_at<=clock_timestamp()"
                    ),
                    scope.params,
                ).rowcount
        if row["expired"] and row["stop_reason"] != "reset":
            if row["status"] in {"queued", "running"}:
                deferred.append(str(scope.run_id))
                continue
            config, _ = contract(db, project, row["contract_version"])
            try:
                reset_run(db, scope, config)
            except BoundaryError:
                raise HTTPException(503, "保留期清理的远端 reset 未完成；证据保留，恢复后重试") from None
            with db.begin() as c:
                audit(c, project, "expire_trace", scope.run_id)
            traces += 1
    return {
        "raw_removed": raw,
        "trace_runs_reset": traces,
        "deferred_active_runs": deferred,
        "complete": not deferred,
    }


def router(db):
    api = APIRouter()

    @api.get("/api/session")
    def session(request: Request):
        return {k: request.state.grant[k] for k in ("id", "projects", "runs", "permissions", "expires_at")}

    @api.post("/api/projects/{project_id}/emergency-stop")
    def emergency_stop(project_id: UUID):
        return stop_project(db, project_id)

    @api.post("/api/projects/{project_id}/resume")
    def resume(project_id: UUID):
        with db.begin() as c:
            result = c.execute(
                text("UPDATE projects SET stopped=false WHERE id=:p AND NOT deleting"), {"p": project_id}
            )
            if not result.rowcount:
                raise HTTPException(409, "项目不存在或正在删除")
            identifier = audit(c, project_id, "resume")
        return {"resumed": True, "audit_id": identifier}

    @api.delete("/api/projects/{project_id}")
    def delete(project_id: UUID):
        return delete_project(db, project_id)

    @api.post("/api/projects/{project_id}/retention")
    def retention(project_id: UUID):
        return retain(db, project_id)

    @api.get("/api/runs/{run_id}/raw-evidence/{observation_id}")
    def raw(run_id: UUID, observation_id: UUID, project_id: UUID):
        with db.connect() as c:
            row = (
                c.execute(
                    text("""SELECT observation_id,payload,expires_at FROM private_evidence
              WHERE project_id=:p AND run_id=:r AND observation_id=:id AND expires_at>clock_timestamp()"""),
                    {"p": project_id, "r": run_id, "id": observation_id},
                )
                .mappings()
                .first()
            )
        if not row:
            raise HTTPException(404, "私有协议证据不存在或已到保留期限")
        return dict(row) | {"credentials_redacted": True}

    return api
