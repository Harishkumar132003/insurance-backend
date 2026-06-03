-- ⚠️  HISTORICAL — DO NOT RUN ON PRODUCTION.
-- One-time dev migration used to add the stage / claimed_amount / remarks
-- columns + `claim_bill_item` table on the `oasysbackup` sandbox, backfill
-- them from `data_json`, then drop `data_json`. The column it backfills from
-- no longer exists in the current schema, so re-running this would fail.
-- Kept here for reference. For greenfield/wipe deploys use
-- `scripts/deploy_schema.sql`.
--
-- Claim-stage normalization: move data_json (bill_breakdown / claimed_amount /
-- remarks / stage) on the pre_auth table into typed columns + a child table,
-- then DROP the data_json column entirely.
--
-- Run on the sandbox:
--   PGPASSWORD=... psql -h localhost -U admin -d oasysbackup -f scripts/claim_stage_normalization.sql

BEGIN;

-- 1. New columns on pre_auth (stage discriminator + claim-stage fields)
ALTER TABLE pre_auth ADD COLUMN IF NOT EXISTS stage VARCHAR NOT NULL DEFAULT 'PRE_AUTH';
ALTER TABLE pre_auth ADD COLUMN IF NOT EXISTS claimed_amount NUMERIC(12,2);
ALTER TABLE pre_auth ADD COLUMN IF NOT EXISTS remarks TEXT;

-- 2. Bill-breakdown child table
CREATE TABLE IF NOT EXISTS claim_bill_item (
    id           BIGSERIAL PRIMARY KEY,
    form_data_id BIGINT NOT NULL REFERENCES pre_auth(id) ON DELETE CASCADE,
    label        VARCHAR NOT NULL,
    amount       NUMERIC(12,2) NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_claim_bill_item_form_data_id ON claim_bill_item(form_data_id);

-- 3. Set the stage discriminator from the old data_json
UPDATE pre_auth SET stage = 'CLAIM'
WHERE data_json->>'stage' = 'CLAIM';
UPDATE pre_auth SET stage = 'PRE_AUTH'
WHERE stage IS NULL OR (data_json->>'stage') IS DISTINCT FROM 'CLAIM';

-- 4. Backfill claimed_amount + remarks for claim rows
UPDATE pre_auth
SET claimed_amount = NULLIF(data_json->>'claimed_amount','')::numeric,
    remarks        = data_json->>'remarks'
WHERE stage = 'CLAIM';

-- 5. Explode bill_breakdown[] into claim_bill_item rows
INSERT INTO claim_bill_item (form_data_id, label, amount, sort_order)
SELECT fd.id,
       elem->>'label',
       NULLIF(elem->>'amount','')::numeric,
       (ord - 1)
FROM pre_auth fd
CROSS JOIN LATERAL jsonb_array_elements(fd.data_json->'bill_breakdown') WITH ORDINALITY AS t(elem, ord)
WHERE fd.stage = 'CLAIM'
  AND jsonb_typeof(fd.data_json->'bill_breakdown') = 'array'
  AND elem->>'label' IS NOT NULL;

-- 6. Drop the now-unused data_json column
ALTER TABLE pre_auth DROP COLUMN data_json;

COMMIT;
