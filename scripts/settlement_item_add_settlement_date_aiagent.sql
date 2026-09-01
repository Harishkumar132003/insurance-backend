-- One-shot aiagent DB fix for `public.settlement_item`.
--
-- Goal:
--   Add `settlement_date` to `public.settlement_item` and populate it from
--   `public.settlement_batch.settlement_date`.
--
-- Scope:
--   - Runs only against `aiagent`
--   - Alters only `public.settlement_item`
--   - Replaces the existing denorm trigger function so future rows stay in sync
--
-- Usage:
--   psql "postgresql://admin:admin123@localhost:5432/aiagent" \
--     -v ON_ERROR_STOP=1 \
--     -f scripts/settlement_item_add_settlement_date_aiagent.sql

BEGIN;

ALTER TABLE public.settlement_item
    ADD COLUMN IF NOT EXISTS settlement_date DATE;

CREATE OR REPLACE FUNCTION public.fill_settlement_item_denorm() RETURNS trigger
LANGUAGE plpgsql AS $func$
BEGIN
    SELECT b.hospital_id, b.settlement_date
      INTO NEW.hospital_id, NEW.settlement_date
      FROM public.settlement_batch b
     WHERE b.id = NEW.batch_id;

    IF NEW.hospitalization_id IS NOT NULL THEN
        SELECT h.uhid
          INTO NEW.uhid
          FROM public.hospitalization h
         WHERE h.id = NEW.hospitalization_id;
    ELSE
        NEW.uhid := NULL;
    END IF;

    RETURN NEW;
END;
$func$;

DROP TRIGGER IF EXISTS trg_fill_settlement_item_denorm ON public.settlement_item;

CREATE TRIGGER trg_fill_settlement_item_denorm
BEFORE INSERT OR UPDATE OF batch_id, hospitalization_id ON public.settlement_item
FOR EACH ROW
EXECUTE FUNCTION public.fill_settlement_item_denorm();

UPDATE public.settlement_item si
   SET settlement_date = b.settlement_date
  FROM public.settlement_batch b
 WHERE b.id = si.batch_id
   AND si.settlement_date IS DISTINCT FROM b.settlement_date;

COMMIT;
