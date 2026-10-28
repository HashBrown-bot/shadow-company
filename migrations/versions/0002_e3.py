"""Independent example stores and scoped E3 execution/receipt/reset records."""

from alembic import op

revision = "0002_e3"
down_revision = "0001_e2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE SCHEMA refund_put;
    CREATE SCHEMA payment_provider;
    CREATE TABLE refund_put.namespaces (
      project_id UUID NOT NULL, run_id UUID NOT NULL, snapshot JSONB NOT NULL,
      PRIMARY KEY(project_id, run_id)
    );
    CREATE TABLE refund_put.payments (
      project_id UUID NOT NULL, run_id UUID NOT NULL, payment_id TEXT NOT NULL,
      amount_minor BIGINT NOT NULL, currency TEXT NOT NULL, refunded_minor BIGINT NOT NULL DEFAULT 0,
      PRIMARY KEY(project_id,run_id,payment_id),
      FOREIGN KEY(project_id,run_id) REFERENCES refund_put.namespaces
    );
    CREATE TABLE refund_put.refunds (
      project_id UUID NOT NULL, run_id UUID NOT NULL, refund_id TEXT NOT NULL,
      payment_id TEXT NOT NULL, amount_minor BIGINT NOT NULL, currency TEXT NOT NULL,
      recipient TEXT NOT NULL, version INT NOT NULL DEFAULT 1, status TEXT NOT NULL,
      approval JSONB, provider_entry_id UUID, created_by TEXT NOT NULL,
      PRIMARY KEY(project_id,run_id,refund_id),
      FOREIGN KEY(project_id,run_id,payment_id) REFERENCES refund_put.payments
    );
    CREATE TABLE refund_put.receipts (
      project_id UUID NOT NULL, run_id UUID NOT NULL, event_id UUID NOT NULL,
      digest TEXT NOT NULL, payload JSONB NOT NULL,
      PRIMARY KEY(project_id,run_id,event_id),
      FOREIGN KEY(project_id,run_id) REFERENCES refund_put.namespaces
    );
    CREATE TABLE payment_provider.namespaces (
      project_id UUID NOT NULL, run_id UUID NOT NULL, snapshot JSONB NOT NULL,
      PRIMARY KEY(project_id,run_id)
    );
    CREATE TABLE payment_provider.payments (
      project_id UUID NOT NULL, run_id UUID NOT NULL, payment_id TEXT NOT NULL,
      amount_minor BIGINT NOT NULL, currency TEXT NOT NULL,
      PRIMARY KEY(project_id,run_id,payment_id),
      FOREIGN KEY(project_id,run_id) REFERENCES payment_provider.namespaces
    );
    CREATE TABLE payment_provider.ledger (
      project_id UUID NOT NULL, run_id UUID NOT NULL, entry_id UUID NOT NULL,
      idempotency_key TEXT NOT NULL, refund_command_id TEXT NOT NULL, payment_id TEXT NOT NULL,
      amount_minor BIGINT NOT NULL, currency TEXT NOT NULL, recipient TEXT NOT NULL,
      request_hash TEXT NOT NULL, status TEXT NOT NULL CHECK(status='succeeded'),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(project_id,run_id,entry_id), UNIQUE(project_id,run_id,idempotency_key),
      FOREIGN KEY(project_id,run_id,payment_id) REFERENCES payment_provider.payments
    );
    CREATE TABLE payment_provider.outbox (
      project_id UUID NOT NULL, run_id UUID NOT NULL, event_id UUID NOT NULL,
      entry_id UUID NOT NULL, payload JSONB NOT NULL,
      put_delivered BOOLEAN NOT NULL DEFAULT false, platform_delivered BOOLEAN NOT NULL DEFAULT false,
      attempts INT NOT NULL DEFAULT 0,
      PRIMARY KEY(project_id,run_id,event_id),
      FOREIGN KEY(project_id,run_id,entry_id) REFERENCES payment_provider.ledger
    );
    CREATE TABLE run_inputs (
      project_id UUID NOT NULL, run_id UUID NOT NULL, content_hash TEXT NOT NULL, payload JSONB NOT NULL,
      reset_at TIMESTAMPTZ, request_key TEXT, request_hash TEXT, UNIQUE(project_id,request_key),
      PRIMARY KEY(project_id,run_id), FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE TABLE webhook_bindings (
      project_id UUID NOT NULL, run_id UUID NOT NULL, binding_id UUID NOT NULL UNIQUE,
      secret_ref TEXT NOT NULL, PRIMARY KEY(project_id,run_id), FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE TABLE webhook_receipts (
      project_id UUID NOT NULL, run_id UUID NOT NULL, event_id UUID NOT NULL,
      digest TEXT NOT NULL, observation_id UUID NOT NULL,
      PRIMARY KEY(project_id,run_id,event_id),
      FOREIGN KEY(project_id,run_id,observation_id) REFERENCES observations
    );
    CREATE TABLE preflights (
      project_id UUID NOT NULL, run_id UUID NOT NULL, contract_hash TEXT NOT NULL,
      passed BOOLEAN NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(project_id,run_id), FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE TABLE reset_audits (
      project_id UUID NOT NULL, run_id UUID NOT NULL, reset_id UUID NOT NULL,
      payload JSONB NOT NULL, content_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(project_id,run_id,reset_id), FOREIGN KEY(project_id,run_id) REFERENCES runs
    );
    CREATE TRIGGER reset_audits_immutable BEFORE UPDATE OR DELETE ON reset_audits
      FOR EACH ROW EXECUTE FUNCTION prevent_evidence_mutation();
    CREATE OR REPLACE FUNCTION prevent_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND TG_TABLE_NAME IN ('events','observations','manifests') THEN
        IF EXISTS (
        SELECT 1 FROM reset_audits WHERE project_id=OLD.project_id AND run_id=OLD.run_id
          AND reset_id::text=current_setting('simulation.reset_id',true)
      ) THEN RETURN OLD; END IF;
      END IF;
      RAISE EXCEPTION 'immutable record: %', TG_TABLE_NAME USING ERRCODE = '23514';
    END; $$;
    CREATE FUNCTION protect_run_input() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.content_hash=OLD.content_hash AND NEW.request_key IS NOT DISTINCT FROM OLD.request_key
        AND NEW.request_hash IS NOT DISTINCT FROM OLD.request_hash AND NEW.payload='{}'::jsonb
        AND NEW.reset_at IS NOT NULL AND EXISTS (
          SELECT 1 FROM reset_audits WHERE project_id=OLD.project_id AND run_id=OLD.run_id
            AND reset_id::text=current_setting('simulation.reset_id',true)
        ) THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'immutable run input' USING ERRCODE='23514';
    END; $$;
    CREATE TRIGGER run_input_immutable BEFORE UPDATE ON run_inputs
      FOR EACH ROW EXECUTE FUNCTION protect_run_input();
    """)


def downgrade():
    op.execute("""
    CREATE OR REPLACE FUNCTION prevent_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'immutable record: %', TG_TABLE_NAME USING ERRCODE = '23514'; END; $$;
    DROP TABLE reset_audits,preflights,webhook_receipts,webhook_bindings,run_inputs;
    DROP FUNCTION protect_run_input();
    DROP SCHEMA refund_put CASCADE;
    DROP SCHEMA payment_provider CASCADE;
    """)
