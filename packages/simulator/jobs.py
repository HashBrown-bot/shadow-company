"""PostgreSQL leases, fencing, cancellation and append-only execution checkpoints."""

import os
from uuid import uuid4

from sqlalchemy import text

from packages.transport.http import BoundaryError
from packages.transport.security import Scope, canonical

LEASE_SECONDS = 3


def journal(c, scope, kind, payload=None, event_id=None):
    return c.execute(
        text(
            "INSERT INTO runtime_journal(project_id,run_id,kind,event_id,payload) VALUES (:p,:r,:k,:e,CAST(:v AS jsonb)) RETURNING sequence"
        ),
        scope.params | {"k": kind, "e": event_id, "v": canonical(payload or {})},
    ).scalar_one()


def claim(db):
    owner = "worker-" + uuid4().hex
    # The session lock prevents replacement while an old process still has remote work in flight.
    guard = db.connect()
    with db.begin() as c:
        candidates = (
            c.execute(
                text(
                    "SELECT * FROM jobs WHERE state='queued' OR (state='leased' AND expires_at<clock_timestamp()) ORDER BY created_at,job_id FOR UPDATE SKIP LOCKED LIMIT 8"
                )
            )
            .mappings()
            .all()
        )
        for row in candidates:
            scope = Scope(project_id=row["project_id"], run_id=row["run_id"])
            key = "worker:" + scope.namespace
            locked = guard.execute(
                text("SELECT pg_try_advisory_lock(hashtextextended(:k,0))"), {"k": key}
            ).scalar_one()
            guard.commit()
            if not locked:
                continue
            epoch = row["lease_epoch"] + 1
            c.execute(
                text(
                    "UPDATE jobs SET state='leased',owner=:o,lease_epoch=:epoch,heartbeat=clock_timestamp(),expires_at=clock_timestamp()+:seconds*interval '1 second',started_at=COALESCE(started_at,clock_timestamp()) WHERE project_id=:p AND run_id=:r"
                ),
                scope.params | {"o": owner, "epoch": epoch, "seconds": LEASE_SECONDS},
            )
            c.execute(
                text(
                    "UPDATE runs SET status='running',verdict='inconclusive' WHERE project_id=:p AND run_id=:r"
                ),
                scope.params,
            )
            journal(
                c,
                scope,
                "lease_acquired",
                {"owner": owner, "pid": os.getpid(), "epoch": epoch, "recovered": row["state"] == "leased"},
            )
            return Lease(db, scope, owner, epoch, guard, key)
    guard.close()
    return None


class Lease:
    def __init__(self, db, scope, owner, epoch, guard, key):
        self.db, self.scope, self.owner, self.epoch, self.guard, self.key = (
            db,
            scope,
            owner,
            epoch,
            guard,
            key,
        )

    def row(self, c):
        row = (
            c.execute(
                text(
                    "SELECT *,clock_timestamp() AS db_now FROM jobs WHERE project_id=:p AND run_id=:r FOR UPDATE"
                ),
                self.scope.params,
            )
            .mappings()
            .one()
        )
        if (
            row["owner"] != self.owner
            or row["lease_epoch"] != self.epoch
            or row["state"] != "leased"
            or row["expires_at"] <= row["db_now"]
        ):
            raise BoundaryError("lease_lost")
        return row

    def heartbeat(self):
        with self.db.begin() as c:
            result = c.execute(
                text(
                    "UPDATE jobs SET heartbeat=clock_timestamp(),expires_at=clock_timestamp()+:seconds*interval '1 second' WHERE project_id=:p AND run_id=:r AND owner=:o AND lease_epoch=:epoch AND state='leased' AND expires_at>clock_timestamp()"
                ),
                self.scope.params | {"o": self.owner, "epoch": self.epoch, "seconds": LEASE_SECONDS},
            )
            return result.rowcount == 1

    def check(self, config, consume=False):
        with self.db.begin() as c:
            row = self.row(c)
            if row["cancel_requested"]:
                raise BoundaryError("cancelled")
            used = row["checkpoint"].get("events_used", 0)
            wall = (row["db_now"] - row["started_at"]).total_seconds()
            if wall >= config.runtime.max_wall_seconds or (consume and used >= config.runtime.max_events):
                raise BoundaryError("budget_exhausted")
            if consume:
                used += 1
            checkpoint = row["checkpoint"] | {
                "events_used": used,
                "wall_seconds": round(wall, 6),
                "llm_calls": row["checkpoint"].get("llm_calls", 0),
                "llm_tokens": row["checkpoint"].get("llm_tokens", 0),
            }
            c.execute(
                text("UPDATE jobs SET checkpoint=CAST(:v AS jsonb) WHERE project_id=:p AND run_id=:r"),
                self.scope.params | {"v": canonical(checkpoint)},
            )
            return checkpoint

    def finish(self, status, reason):
        with self.db.begin() as c:
            row = self.row(c)
            if row["cancel_requested"]:
                status, reason = "cancelled", "cancelled"
            checkpoint = row["checkpoint"] | {
                "wall_seconds": (row["db_now"] - row["started_at"]).total_seconds(),
                "execution_finished": status == "completed",
            }
            c.execute(
                text(
                    "UPDATE jobs SET state=:s,checkpoint=CAST(:v AS jsonb),heartbeat=clock_timestamp() WHERE project_id=:p AND run_id=:r"
                ),
                self.scope.params | {"s": status, "v": canonical(checkpoint)},
            )
            c.execute(
                text(
                    "UPDATE runs SET status=:s,stop_reason=:reason,verdict='inconclusive' WHERE project_id=:p AND run_id=:r"
                ),
                self.scope.params | {"s": status, "reason": reason},
            )
            if status != "completed":
                c.execute(
                    text(
                        "UPDATE event_dispatches SET state='cancelled' WHERE project_id=:p AND run_id=:r AND state='pending'"
                    ),
                    self.scope.params,
                )
            journal(
                c, self.scope, "run_stopped", {"status": status, "reason": reason, "checkpoint": checkpoint}
            )

    def close(self):
        try:
            self.guard.execute(text("SELECT pg_advisory_unlock(hashtextextended(:k,0))"), {"k": self.key})
            self.guard.commit()
        finally:
            self.guard.close()


def cancel(db, scope):
    with db.begin() as c:
        row = c.execute(
            text("SELECT state FROM jobs WHERE project_id=:p AND run_id=:r FOR UPDATE"), scope.params
        ).scalar_one_or_none()
        if row is None:
            raise BoundaryError("job_not_found")
        if row not in {"queued", "leased"}:
            return {"cancel_requested": False, "state": row}
        c.execute(
            text("UPDATE jobs SET cancel_requested=true WHERE project_id=:p AND run_id=:r"), scope.params
        )
        journal(c, scope, "cancel_requested")
        if row == "queued":
            c.execute(
                text("UPDATE jobs SET state='cancelled' WHERE project_id=:p AND run_id=:r"), scope.params
            )
            c.execute(
                text(
                    "UPDATE runs SET status='cancelled',verdict='inconclusive',stop_reason='cancelled' WHERE project_id=:p AND run_id=:r"
                ),
                scope.params,
            )
        return {"cancel_requested": True, "state": row}
