"""E6 immutable replay assets and completion seals; old manifests stay untouched."""

from alembic import op

revision = "0005_e6"
down_revision = "0004_e5"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE replay_assets (
      project_id UUID NOT NULL, run_id UUID NOT NULL,
      kind TEXT NOT NULL CHECK(kind IN ('snapshot','actors','faults')),
      content_hash TEXT NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'), payload JSONB NOT NULL,
      PRIMARY KEY(project_id,run_id,kind), FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE TABLE replay_seals (
      project_id UUID NOT NULL, run_id UUID NOT NULL,
      parent_hash TEXT NOT NULL CHECK(parent_hash ~ '^[0-9a-f]{64}$'),
      content_hash TEXT NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'), payload JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(project_id,run_id), FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE TRIGGER replay_assets_immutable BEFORE UPDATE OR DELETE ON replay_assets
      FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
    CREATE TRIGGER replay_seals_immutable BEFORE UPDATE OR DELETE ON replay_seals
      FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
    CREATE OR REPLACE FUNCTION prevent_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND TG_TABLE_NAME IN
        ('events','observations','manifests','evaluations','runtime_journal','replay_assets','replay_seals') THEN
        IF EXISTS (SELECT 1 FROM reset_audits WHERE project_id=OLD.project_id AND run_id=OLD.run_id
          AND reset_id::text=current_setting('simulation.reset_id',true)) THEN RETURN OLD; END IF;
      END IF;
      RAISE EXCEPTION 'immutable record: %', TG_TABLE_NAME USING ERRCODE = '23514';
    END; $$;
    """)


def downgrade():
    op.execute("DROP TABLE replay_seals,replay_assets")
    op.execute("""
    CREATE OR REPLACE FUNCTION prevent_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND TG_TABLE_NAME IN ('events','observations','manifests','evaluations','runtime_journal') THEN
        IF EXISTS (SELECT 1 FROM reset_audits WHERE project_id=OLD.project_id AND run_id=OLD.run_id
          AND reset_id::text=current_setting('simulation.reset_id',true)) THEN RETURN OLD; END IF;
      END IF;
      RAISE EXCEPTION 'immutable record: %', TG_TABLE_NAME USING ERRCODE = '23514';
    END; $$;
    """)
