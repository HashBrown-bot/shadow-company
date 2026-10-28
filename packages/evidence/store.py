from uuid import uuid4

from sqlalchemy import text

from packages.transport.security import canonical, digest, redact


def append(conn, scope, source, external_id, kind, payload):
    raw_headers = payload.get("request", {}).get("headers", {}) if isinstance(payload, dict) else {}
    secrets = [
        v.removeprefix("Bearer ")
        for k, v in raw_headers.items()
        if k.lower() in {"authorization", "cookie", "x-api-key"} and isinstance(v, str)
    ]
    clean = redact(payload, secrets)
    identifier = uuid4()
    conn.execute(
        text("""INSERT INTO observations
      (project_id,run_id,observation_id,source,external_id,evidence_kind,raw_ref,digest,captured_at,payload)
      VALUES (:p,:r,:id,:source,:external,:kind,:ref,:digest,now(),CAST(:payload AS jsonb))"""),
        scope.params
        | {
            "id": identifier,
            "source": source,
            "external": external_id,
            "kind": kind,
            "ref": f"private://postgres/{scope.project_id}/{scope.run_id}/{identifier}",
            "digest": digest(clean),
            "payload": canonical(clean),
        },
    )
    conn.execute(
        text("""INSERT INTO private_evidence(project_id,run_id,observation_id,payload,expires_at)
        SELECT :p,:r,:id,CAST(:payload AS jsonb),clock_timestamp() +
          ((c.config->'artifacts'->>'raw_retention_days')::int * interval '1 day')
        FROM runs r JOIN contracts c ON c.project_id=r.project_id AND c.version=r.contract_version
        WHERE r.project_id=:p AND r.run_id=:r"""),
        scope.params | {"id": identifier, "payload": canonical(clean)},
    )
    return str(identifier)
