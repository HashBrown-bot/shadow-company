"""E7 immutable actor policies, call audit, paired experiment membership and reviews."""

from alembic import op

revision = "0006_e7"
down_revision = "0005_e6"
branch_labels = None
depends_on = None


def guard(tables):
    names = ",".join("'" + name + "'" for name in tables)
    op.execute(f"""
    CREATE OR REPLACE FUNCTION prevent_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND TG_TABLE_NAME IN ({names}) THEN
        IF EXISTS (SELECT 1 FROM reset_audits WHERE project_id=OLD.project_id AND run_id=OLD.run_id
          AND reset_id::text=current_setting('simulation.reset_id',true)) THEN RETURN OLD; END IF;
      END IF;
      RAISE EXCEPTION 'immutable record: %', TG_TABLE_NAME USING ERRCODE = '23514';
    END; $$;
    """)


OLD = [
    "events",
    "observations",
    "manifests",
    "evaluations",
    "runtime_journal",
    "replay_assets",
    "replay_seals",
]


def upgrade():
    op.execute("""
    CREATE TABLE actor_policies (
      project_id UUID NOT NULL, run_id UUID NOT NULL,
      content_hash TEXT NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'), payload JSONB NOT NULL,
      PRIMARY KEY(project_id,run_id), FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE TABLE actor_calls (
      project_id UUID NOT NULL, run_id UUID NOT NULL, call_id UUID NOT NULL,
      phase TEXT NOT NULL CHECK(phase IN ('reserved','returned','rejected')),
      created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      content_hash TEXT NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'), payload JSONB NOT NULL,
      PRIMARY KEY(project_id,run_id,call_id,phase), FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE INDEX actor_calls_scope_time ON actor_calls(project_id,run_id,created_at);
    CREATE TABLE experiments (
      project_id UUID NOT NULL REFERENCES projects(id), experiment_id UUID NOT NULL,
      request_key TEXT NOT NULL, content_hash TEXT NOT NULL, payload JSONB NOT NULL,
      PRIMARY KEY(project_id,experiment_id), UNIQUE(project_id,request_key)
    );
    CREATE TABLE experiment_runs (
      project_id UUID NOT NULL, run_id UUID NOT NULL, experiment_id UUID NOT NULL,
      seed BIGINT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('rule','hybrid')),
      PRIMARY KEY(project_id,run_id), UNIQUE(project_id,experiment_id,seed,mode),
      FOREIGN KEY(project_id,experiment_id) REFERENCES experiments,
      FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE TABLE finding_reviews (
      project_id UUID NOT NULL, run_id UUID NOT NULL, review_id UUID NOT NULL,
      finding_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      content_hash TEXT NOT NULL, payload JSONB NOT NULL,
      PRIMARY KEY(project_id,run_id,review_id), UNIQUE(project_id,run_id,finding_id),
      FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    """)
    for table in ("actor_policies", "actor_calls", "experiments", "experiment_runs", "finding_reviews"):
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
          FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation()""")
    guard(OLD + ["actor_policies", "actor_calls", "finding_reviews"])


def downgrade():
    op.execute("DROP TABLE finding_reviews,experiment_runs,experiments,actor_calls,actor_policies")
    guard(OLD)
