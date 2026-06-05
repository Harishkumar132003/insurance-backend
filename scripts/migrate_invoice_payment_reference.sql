-- Migrate the invoice flow:
--   1. Move reference_id from `invoice` onto `invoice_payment`
--      (backfill earliest payment per invoice from the old column).
--   2. Drop `invoice.reference_id`.
--   3. Re-derive `invoice.status` from each invoice's payments using the
--      new enum (PAID / PARTIALLY_PAID / UNPAID).
--
-- Idempotent: safe to re-run.
--
-- Usage:
--   docker exec -i -e PGPASSWORD=admin123 oasys-postgres \
--     psql -U admin -d oasys -v ON_ERROR_STOP=1 \
--     < scripts/migrate_invoice_payment_reference.sql

BEGIN;

-- 1. Add reference_id + updated_at to invoice_payment (idempotent).
ALTER TABLE invoice_payment ADD COLUMN IF NOT EXISTS reference_id VARCHAR;
ALTER TABLE invoice_payment
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- 2. Backfill earliest payment per invoice from invoice.reference_id, then
--    drop the old column. Wrapped in a DO block so re-runs after the drop
--    are no-ops.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'invoice' AND column_name = 'reference_id'
  ) THEN
    UPDATE invoice_payment ip
    SET reference_id = i.reference_id
    FROM invoice i
    WHERE ip.invoice_id = i.id
      AND ip.sort_order = 0
      AND ip.reference_id IS NULL
      AND i.reference_id IS NOT NULL
      AND TRIM(i.reference_id) <> '';

    ALTER TABLE invoice DROP COLUMN reference_id;
  END IF;
END $$;

-- 3. Re-derive invoice.status from payments using the new enum.
WITH totals AS (
  SELECT i.id,
         i.insurer_amount,
         COALESCE((SELECT SUM(amount) FROM invoice_payment WHERE invoice_id = i.id), 0) AS paid
  FROM invoice i
)
UPDATE invoice i
SET status = CASE
  WHEN t.paid >= t.insurer_amount AND t.insurer_amount > 0 THEN 'PAID'
  WHEN t.paid > 0 THEN 'PARTIALLY_PAID'
  ELSE 'UNPAID'
END
FROM totals t
WHERE i.id = t.id;

COMMIT;
