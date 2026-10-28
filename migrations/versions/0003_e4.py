"""E4 observed execution context, customer ownership and durable evaluations."""

from alembic import op

revision = "0003_e4"
down_revision = "0002_e3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE refund_put.namespaces ADD COLUMN behavior TEXT NOT NULL DEFAULT 'fixed';
    ALTER TABLE refund_put.payments ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'customer_a';
    ALTER TABLE refund_put.refunds ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'customer_a';
    ALTER TABLE payment_provider.ledger ADD COLUMN command_version INT;
    ALTER TABLE payment_provider.ledger ADD COLUMN approval JSONB;
    CREATE TABLE evaluations (
      project_id UUID NOT NULL, run_id UUID NOT NULL, evaluation_id UUID NOT NULL,
      evidence_hash TEXT NOT NULL, rules_hash TEXT NOT NULL, payload JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(project_id,run_id,evaluation_id),
      FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE INDEX evaluations_scope ON evaluations(project_id,run_id,created_at);
    ALTER TABLE check_results ADD COLUMN evaluation_id UUID;
    ALTER TABLE check_results ADD CONSTRAINT check_evaluation_scope
      FOREIGN KEY(project_id,run_id,evaluation_id) REFERENCES evaluations;
    CREATE TRIGGER evaluations_immutable BEFORE UPDATE OR DELETE ON evaluations
      FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
    CREATE OR REPLACE FUNCTION prevent_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND TG_TABLE_NAME IN ('events','observations','manifests','evaluations') THEN
        IF EXISTS (SELECT 1 FROM reset_audits WHERE project_id=OLD.project_id AND run_id=OLD.run_id
          AND reset_id::text=current_setting('simulation.reset_id',true)) THEN RETURN OLD; END IF;
      END IF;
      RAISE EXCEPTION 'immutable record: %', TG_TABLE_NAME USING ERRCODE = '23514';
    END; $$;
    """)


def downgrade():
    op.execute("""
    ALTER TABLE check_results DROP CONSTRAINT check_evaluation_scope;
    ALTER TABLE check_results DROP COLUMN evaluation_id;
    DROP TABLE evaluations;
    ALTER TABLE payment_provider.ledger DROP COLUMN approval, DROP COLUMN command_version;
    ALTER TABLE refund_put.refunds DROP COLUMN owner_id;
    ALTER TABLE refund_put.payments DROP COLUMN owner_id;
    ALTER TABLE refund_put.namespaces DROP COLUMN behavior;
    """)
