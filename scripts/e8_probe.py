"""Acceptance-only process/evidence faults in the verifier-owned, disposable database.

No API backdoor and no fabricated response: the browser reads actual backend results.
"""

import json
import os
import signal
import sys
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from packages.transport.security import digest


def main():
    session = json.loads(Path(".local/e8-session.json").read_text())
    if not session["database"].startswith(("sim_e8_acceptance_", "sim_e9_acceptance_")):
        raise RuntimeError("only owned E8 acceptance DB permitted")
    pid = session["worker_pid"]
    mode = sys.argv[1]
    if mode in {"pause", "resume"}:
        if os.getpgid(pid) != pid:
            raise RuntimeError("not the owned worker process group")
        os.killpg(pid, signal.SIGSTOP if mode == "pause" else signal.SIGCONT)
        print(mode + " owned worker group")
    elif mode == "lose-ledger":
        p, r = UUID(sys.argv[2]), UUID(sys.argv[3])
        audit = uuid4()
        payload = {"purpose": "E8 audited negative evidence-loss browser test"}
        with psycopg.connect("postgresql://sim@127.0.0.1:55432/" + session["database"]) as c:
            c.execute(
                "INSERT INTO reset_audits(project_id,run_id,reset_id,payload,content_hash) VALUES (%s,%s,%s,%s,%s)",
                [p, r, audit, Jsonb(payload), digest(payload)],
            )
            c.execute("SELECT set_config('simulation.reset_id',%s,true)", [str(audit)])
            cur = c.execute(
                "DELETE FROM observations WHERE project_id=%s AND run_id=%s AND source='provider_ledger'",
                [p, r],
            )
            assert cur.rowcount > 0
        print("removed only scoped persisted provider_ledger for negative test")
    else:
        raise ValueError("unknown probe")


if __name__ == "__main__":
    main()
