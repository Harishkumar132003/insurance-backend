-- Additive migration: invoice + invoice_payment tables.
-- Run on production (and any environment already on the post-normalization
-- schema) to enable the Raise Invoice flow without touching existing data.
--
-- Idempotent: safe to re-run.
--
-- Usage:
--   PGPASSWORD=... psql -h <host> -U admin -d <db> -v ON_ERROR_STOP=1 \
--     -f scripts/add_invoice_tables.sql

BEGIN;

-- 1. Invoice (one per claim case; created when the hospital raises an invoice
--    on a CLAIM_APPROVED / CLAIM_PARTIALLY_APPROVED case).
CREATE TABLE IF NOT EXISTS invoice (
    id                  BIGSERIAL PRIMARY KEY,
    claim_case_id       UUID NOT NULL UNIQUE
                          REFERENCES hospitalization(id) ON DELETE CASCADE,
    insurer_invoice_id  VARCHAR NOT NULL,
    insurer_amount      NUMERIC(12,2) NOT NULL,
    reference_id        VARCHAR,
    status              VARCHAR NOT NULL DEFAULT 'INVOICE_RAISED',
                          -- INVOICE_RAISED | PAID | UNPAID
    created_by_user_id  UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_invoice_status ON invoice(status);

-- 2. Invoice payments (N per invoice; manually captured by the hospital).
CREATE TABLE IF NOT EXISTS invoice_payment (
    id            BIGSERIAL PRIMARY KEY,
    invoice_id    BIGINT NOT NULL REFERENCES invoice(id) ON DELETE CASCADE,
    payment_date  DATE NOT NULL,
    amount        NUMERIC(12,2) NOT NULL,
    note          TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_invoice_payment_invoice_id
  ON invoice_payment(invoice_id);

COMMIT;
