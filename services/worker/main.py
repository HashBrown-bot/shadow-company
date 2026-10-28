"""Independent supervised Worker. Each job attempt owns a fenced PostgreSQL lease."""

import argparse
import json
import signal
import subprocess
import sys
import traceback
from pathlib import Path
from threading import Event, Thread

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from packages.simulator.e3 import execute_run
from packages.simulator.jobs import claim
from packages.transport.http import BoundaryError
from services.api.database import check_database, make_engine


def work_once(db):
    lease = claim(db)
    if not lease:
        return False
    stop = Event()

    def heartbeat():
        while not stop.wait(0.5):
            try:
                if not lease.heartbeat():
                    return
            except SQLAlchemyError:
                return

    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        with db.connect() as c:
            kind = c.execute(
                text("SELECT payload->>'kind' FROM run_inputs WHERE project_id=:p AND run_id=:r"),
                lease.scope.params,
            ).scalar()
        if kind not in {"e5_runtime", "e6_replay"} and lease.epoch > 1:
            lease.finish("failed", "remote_outcome_unknown_legacy_scope")
            return True
        if kind in {"e5_runtime", "e6_replay"}:
            from packages.simulator.e5 import execute_run as execute_e5

            execute_e5(db, lease)
        else:
            if kind == "e4_rules":
                from packages.simulator.e4 import execute_run as execute_e4

                execute_e4(db, lease.scope)
            else:
                execute_run(db, lease.scope)
            # E3/E4 retain their original evidence and compatibility paths.
            with db.begin() as c:
                c.execute(
                    text(
                        "UPDATE jobs SET state='completed',heartbeat=clock_timestamp(),checkpoint=checkpoint || CAST(:checkpoint AS jsonb) WHERE project_id=:p AND run_id=:r AND owner=:o AND lease_epoch=:epoch"
                    ),
                    lease.scope.params
                    | {"o": lease.owner, "epoch": lease.epoch, "checkpoint": '{"execution_finished":true}'},
                )
    except (BoundaryError, SQLAlchemyError, KeyError, ValueError, TypeError) as error:
        print(
            json.dumps(
                {
                    "event": "execution_error",
                    "type": type(error).__name__,
                    "frames": [
                        {"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
                        for f in traceback.extract_tb(error.__traceback__)
                    ],
                    "sqlstate": getattr(getattr(error, "orig", None), "sqlstate", None),
                }
            ),
            flush=True,
        )
        try:
            lease.finish("failed", str(error) if isinstance(error, BoundaryError) else "execution_incomplete")
        except (BoundaryError, SQLAlchemyError):
            pass
    finally:
        stop.set()
        thread.join(timeout=2)
        lease.close()
    return True


def main():
    parser = argparse.ArgumentParser(description="E7 Worker：租约、checkpoint、取消和真实子进程重启")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    db = make_engine()
    try:
        check_database(db)
    except (SQLAlchemyError, RuntimeError):
        print(json.dumps({"status": "unavailable", "code": "database_unavailable"}))
        return 2
    if args.once:
        try:
            return 10 if work_once(db) else 0
        finally:
            db.dispose()
    db.dispose()
    print(json.dumps({"status": "ready", "phase": "E7", "execution_enabled": True}), flush=True)
    if args.check:
        return 0
    stopped = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    while not stopped.is_set():
        child = subprocess.Popen([sys.executable, "-m", "services.worker.main", "--once"])
        while child.poll() is None and not stopped.wait(0.1):
            pass
        if stopped.is_set() and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=6)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if child.returncode not in {0, 10}:
            print(
                json.dumps(
                    {
                        "event": "worker_process_exited",
                        "pid": child.pid,
                        "exit_code": child.returncode,
                        "recovery": "lease_expiry_then_evidence_verification",
                    }
                ),
                flush=True,
            )
        if child.returncode == 0:
            stopped.wait(0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
