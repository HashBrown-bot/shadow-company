"""Local access lifecycle, private evidence expiry and independent credit-note example."""

from alembic import op

revision = "0007_e9"
down_revision = "0006_e7"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE projects ADD COLUMN stopped BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE projects ADD COLUMN deleting BOOLEAN NOT NULL DEFAULT false;
    CREATE TABLE lifecycle_audits (
      audit_id UUID PRIMARY KEY, project_id UUID NOT NULL, run_id UUID,
      operation TEXT NOT NULL CHECK(operation IN ('delete_project','expire_raw','expire_trace','emergency_stop','resume')),
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      record_count BIGINT NOT NULL DEFAULT 0
    );
    CREATE TABLE private_evidence (
      project_id UUID NOT NULL, run_id UUID NOT NULL, observation_id UUID NOT NULL,
      payload JSONB NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
      PRIMARY KEY(project_id,run_id,observation_id), FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE INDEX private_evidence_expiry ON private_evidence(expires_at);
    CREATE TRIGGER private_evidence_immutable BEFORE UPDATE OR DELETE ON private_evidence
      FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
    CREATE SCHEMA credit_note;
    CREATE TABLE credit_note.namespaces (
      project_id UUID NOT NULL, run_id UUID NOT NULL, snapshot JSONB NOT NULL,
      variant TEXT NOT NULL DEFAULT 'fixed', PRIMARY KEY(project_id,run_id)
    );
    CREATE TABLE credit_note.notes (
      project_id UUID NOT NULL, run_id UUID NOT NULL, note_id TEXT NOT NULL, document JSONB NOT NULL,
      PRIMARY KEY(project_id,run_id,note_id), FOREIGN KEY(project_id,run_id) REFERENCES credit_note.namespaces
    );
    CREATE TABLE credit_note.receipts (
      project_id UUID NOT NULL, run_id UUID NOT NULL, event_id UUID NOT NULL, digest TEXT NOT NULL,
      PRIMARY KEY(project_id,run_id,event_id), FOREIGN KEY(project_id,run_id) REFERENCES credit_note.namespaces
    );
    ALTER TABLE payment_provider.namespaces ADD COLUMN put_origin TEXT NOT NULL DEFAULT 'http://127.0.0.1:8001';
    CREATE OR REPLACE FUNCTION prevent_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        IF EXISTS (SELECT 1 FROM lifecycle_audits WHERE project_id=OLD.project_id
          AND audit_id::text=current_setting('simulation.lifecycle_id',true)
          AND operation='delete_project') THEN
          RETURN OLD;
        END IF;
        IF TG_TABLE_NAME='private_evidence' THEN
          IF EXISTS (SELECT 1 FROM lifecycle_audits WHERE project_id=OLD.project_id AND run_id=OLD.run_id
            AND operation='expire_raw' AND audit_id::text=current_setting('simulation.lifecycle_id',true)) THEN
            RETURN OLD;
          END IF;
        END IF;
        IF TG_TABLE_NAME IN ('events','observations','manifests','evaluations','runtime_journal',
            'replay_assets','replay_seals','actor_policies','actor_calls','finding_reviews','private_evidence') THEN
          IF EXISTS (SELECT 1 FROM reset_audits WHERE project_id=OLD.project_id AND run_id=OLD.run_id
            AND reset_id::text=current_setting('simulation.reset_id',true)) THEN RETURN OLD; END IF;
        END IF;
      END IF;
      RAISE EXCEPTION 'immutable record: %', TG_TABLE_NAME USING ERRCODE = '23514';
    END; $$;
    CREATE FUNCTION prevent_lifecycle_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'immutable lifecycle audit' USING ERRCODE='23514'; END; $$;
    CREATE TRIGGER lifecycle_immutable BEFORE UPDATE OR DELETE ON lifecycle_audits
      FOR EACH ROW EXECUTE FUNCTION prevent_lifecycle_mutation();
    """)


def downgrade():
    op.execute("""
    DROP TABLE private_evidence, lifecycle_audits;
    DROP FUNCTION prevent_lifecycle_mutation();
    DROP TABLE credit_note.receipts,credit_note.notes,credit_note.namespaces;
    DROP SCHEMA credit_note;
    ALTER TABLE payment_provider.namespaces DROP COLUMN put_origin;
    ALTER TABLE projects DROP COLUMN stopped, DROP COLUMN deleting;
    """)
    # Restore the immediately preceding guard without changing any old migration.
    from importlib import import_module

    previous = import_module("migrations.versions.0006_e7")
    previous.guard(previous.OLD + ["actor_policies", "actor_calls", "finding_reviews"])
