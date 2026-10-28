"""E5 durable scheduling, fenced leases and independent fault/transport evidence."""

from alembic import op

revision = "0004_e5"
down_revision = "0003_e4"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE jobs ADD COLUMN lease_epoch BIGINT NOT NULL DEFAULT 0;
    ALTER TABLE jobs ADD COLUMN started_at TIMESTAMPTZ;
    ALTER TABLE events ADD COLUMN priority INT NOT NULL DEFAULT 0;
    ALTER TABLE actions ADD COLUMN start_sequence BIGINT;
    ALTER TABLE actions ADD COLUMN end_sequence BIGINT;
    CREATE TABLE event_dispatches (
      project_id UUID NOT NULL, run_id UUID NOT NULL, event_id UUID NOT NULL,
      state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','inflight','done','unknown','cancelled')),
      lease_epoch BIGINT, attempts INT NOT NULL DEFAULT 0, result JSONB,
      PRIMARY KEY(project_id,run_id,event_id),
      FOREIGN KEY(project_id,run_id,event_id) REFERENCES events
    );
    CREATE TABLE runtime_journal (
      project_id UUID NOT NULL, run_id UUID NOT NULL, sequence BIGINT GENERATED ALWAYS AS IDENTITY,
      kind TEXT NOT NULL, event_id UUID, wall_time TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      payload JSONB NOT NULL,
      PRIMARY KEY(project_id,run_id,sequence), FOREIGN KEY(project_id,run_id) REFERENCES runs,
      FOREIGN KEY(project_id,run_id,event_id) REFERENCES events
    );
    CREATE TRIGGER runtime_journal_immutable BEFORE UPDATE OR DELETE ON runtime_journal
      FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
    CREATE OR REPLACE FUNCTION prevent_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND TG_TABLE_NAME IN ('events','observations','manifests','evaluations','runtime_journal') THEN
        IF EXISTS (SELECT 1 FROM reset_audits WHERE project_id=OLD.project_id AND run_id=OLD.run_id
          AND reset_id::text=current_setting('simulation.reset_id',true)) THEN RETURN OLD; END IF;
      END IF;
      RAISE EXCEPTION 'immutable record: %', TG_TABLE_NAME USING ERRCODE = '23514';
    END; $$;
    """)
    for schema in ("payment_provider", "refund_put"):
        op.execute(f"""
        CREATE TABLE {schema}.fault_plans (
          project_id UUID NOT NULL, run_id UUID NOT NULL, fault_id TEXT NOT NULL,
          payload JSONB NOT NULL, PRIMARY KEY(project_id,run_id,fault_id),
          FOREIGN KEY(project_id,run_id) REFERENCES {schema}.namespaces
        );
        CREATE TABLE {schema}.audit (
          project_id UUID NOT NULL, run_id UUID NOT NULL, sequence BIGINT GENERATED ALWAYS AS IDENTITY,
          kind TEXT NOT NULL, wall_time TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), payload JSONB NOT NULL,
          PRIMARY KEY(project_id,run_id,sequence), FOREIGN KEY(project_id,run_id) REFERENCES {schema}.namespaces
        );
        CREATE TRIGGER audit_append_only BEFORE UPDATE ON {schema}.audit
          FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
        CREATE TRIGGER fault_plan_immutable BEFORE UPDATE ON {schema}.fault_plans
          FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
        """)
    op.execute("ALTER TABLE refund_put.refunds ADD COLUMN provider_key TEXT")


def downgrade():
    op.execute("""
    DROP TABLE event_dispatches,runtime_journal;
    ALTER TABLE actions DROP COLUMN start_sequence,DROP COLUMN end_sequence;
    ALTER TABLE events DROP COLUMN priority;
    ALTER TABLE jobs DROP COLUMN lease_epoch,DROP COLUMN started_at;
    ALTER TABLE refund_put.refunds DROP COLUMN provider_key;
    DROP TABLE refund_put.audit,refund_put.fault_plans,payment_provider.audit,payment_provider.fault_plans;
    """)
