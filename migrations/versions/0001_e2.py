"""E2 scoped persistence, immutable contracts and append-only observations."""

from alembic import op

revision = "0001_e2"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE projects (
        id UUID PRIMARY KEY,
        name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
        ownership TEXT NOT NULL CHECK (ownership = 'local_team'),
        local_access_policy TEXT NOT NULL CHECK (local_access_policy = 'loopback_only'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE contracts (
        project_id UUID NOT NULL REFERENCES projects(id),
        version TEXT NOT NULL,
        schema_version TEXT NOT NULL CHECK (schema_version = '0.2'),
        content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
        config JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (project_id, version),
        UNIQUE (project_id, version, content_hash)
    );
    CREATE TABLE runs (
        project_id UUID NOT NULL,
        run_id UUID NOT NULL,
        contract_version TEXT NOT NULL,
        contract_hash TEXT NOT NULL,
        put_version TEXT NOT NULL,
        seed BIGINT NOT NULL CHECK (seed >= 0),
        time_mode TEXT NOT NULL CHECK (time_mode IN ('realtime', 'event_compressed')),
        status TEXT NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued','running','completed','failed','cancelled')),
        verdict TEXT NOT NULL DEFAULT 'inconclusive'
            CHECK (verdict IN ('pass','fail','inconclusive','not_applicable')),
        manifest_hash TEXT CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
        stop_reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (project_id, run_id),
        FOREIGN KEY (project_id, contract_version, contract_hash)
            REFERENCES contracts(project_id, version, content_hash)
    );
    CREATE TABLE events (
        project_id UUID NOT NULL,
        run_id UUID NOT NULL,
        event_id UUID NOT NULL,
        parent_id UUID,
        causation_id UUID,
        business_object_id TEXT NOT NULL,
        simulation_time TIMESTAMPTZ NOT NULL,
        wall_time TIMESTAMPTZ NOT NULL,
        ingress_sequence BIGINT NOT NULL CHECK (ingress_sequence >= 0),
        payload JSONB NOT NULL,
        PRIMARY KEY (project_id, run_id, event_id),
        UNIQUE (project_id, run_id, ingress_sequence),
        FOREIGN KEY (project_id, run_id) REFERENCES runs(project_id, run_id),
        FOREIGN KEY (project_id, run_id, parent_id) REFERENCES events(project_id, run_id, event_id),
        FOREIGN KEY (project_id, run_id, causation_id) REFERENCES events(project_id, run_id, event_id)
    );
    CREATE TABLE actions (
        project_id UUID NOT NULL,
        run_id UUID NOT NULL,
        action_id UUID NOT NULL,
        event_id UUID NOT NULL,
        actor_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        request_ref TEXT NOT NULL,
        start_time TIMESTAMPTZ NOT NULL,
        end_time TIMESTAMPTZ,
        PRIMARY KEY (project_id, run_id, action_id),
        FOREIGN KEY (project_id, run_id, event_id) REFERENCES events(project_id, run_id, event_id)
    );
    CREATE TABLE observations (
        project_id UUID NOT NULL,
        run_id UUID NOT NULL,
        observation_id UUID NOT NULL,
        source TEXT NOT NULL,
        external_id TEXT NOT NULL,
        evidence_kind TEXT NOT NULL CHECK (evidence_kind IN ('product_observation','dependency_evidence')),
        raw_ref TEXT NOT NULL,
        digest TEXT NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
        captured_at TIMESTAMPTZ NOT NULL,
        payload JSONB NOT NULL,
        PRIMARY KEY (project_id, run_id, observation_id),
        FOREIGN KEY (project_id, run_id) REFERENCES runs(project_id, run_id)
    );
    CREATE INDEX observations_source ON observations(project_id, run_id, source, external_id);
    CREATE TABLE check_results (
        project_id UUID NOT NULL,
        run_id UUID NOT NULL,
        check_id UUID NOT NULL,
        rule_id TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        object_id TEXT NOT NULL,
        verdict TEXT NOT NULL CHECK (verdict IN ('pass','fail','inconclusive','not_applicable')),
        reason TEXT NOT NULL CHECK (length(reason) > 0),
        evidence_refs JSONB NOT NULL,
        evaluated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (project_id, run_id, check_id),
        FOREIGN KEY (project_id, run_id) REFERENCES runs(project_id, run_id)
    );
    CREATE TABLE findings (
        project_id UUID NOT NULL,
        run_id UUID NOT NULL,
        finding_id UUID NOT NULL,
        check_id UUID NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('critical','high','medium','low')),
        attribution TEXT NOT NULL CHECK (attribution IN ('product_defect','expected_rejection','actor_error',
            'adapter_error','environment_error','dependency_failure','undetermined')),
        confirmation TEXT NOT NULL CHECK (confirmation IN ('unconfirmed','confirmed','dismissed')),
        dedup_key TEXT NOT NULL,
        payload JSONB NOT NULL,
        PRIMARY KEY (project_id, run_id, finding_id),
        UNIQUE (project_id, run_id, dedup_key),
        FOREIGN KEY (project_id, run_id, check_id) REFERENCES check_results(project_id, run_id, check_id)
    );
    CREATE TABLE manifests (
        project_id UUID NOT NULL,
        run_id UUID NOT NULL,
        content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
        payload JSONB NOT NULL,
        PRIMARY KEY (project_id, run_id),
        FOREIGN KEY (project_id, run_id) REFERENCES runs(project_id, run_id)
    );
    CREATE TABLE jobs (
        project_id UUID NOT NULL,
        run_id UUID NOT NULL,
        job_id UUID NOT NULL,
        idempotency_key TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','leased','completed','failed','cancelled')),
        owner TEXT,
        expires_at TIMESTAMPTZ,
        heartbeat TIMESTAMPTZ,
        checkpoint JSONB NOT NULL DEFAULT '{}',
        cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (project_id, job_id),
        UNIQUE (project_id, idempotency_key),
        UNIQUE (project_id, run_id),
        FOREIGN KEY (project_id, run_id) REFERENCES runs(project_id, run_id),
        CHECK (state != 'leased' OR (owner IS NOT NULL AND expires_at IS NOT NULL AND heartbeat IS NOT NULL))
    );
    CREATE INDEX jobs_claim ON jobs(state, expires_at, created_at);
    CREATE FUNCTION prevent_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'immutable record: %', TG_TABLE_NAME USING ERRCODE = '23514';
    END;
    $$;
    CREATE TRIGGER contracts_immutable BEFORE UPDATE OR DELETE ON contracts
        FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
    CREATE TRIGGER observations_append_only BEFORE UPDATE OR DELETE ON observations
        FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
    CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events
        FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
    CREATE TRIGGER manifests_immutable BEFORE UPDATE OR DELETE ON manifests
        FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
    """)


def downgrade():
    for table in [
        "jobs",
        "manifests",
        "findings",
        "check_results",
        "observations",
        "actions",
        "events",
        "runs",
        "contracts",
        "projects",
    ]:
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION prevent_evidence_mutation()")
