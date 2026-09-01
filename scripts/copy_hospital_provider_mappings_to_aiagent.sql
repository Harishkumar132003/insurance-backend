-- One-shot copy script for `public.hospital_provider_mappings` into `aiagent`.
--
-- Goal:
--   Create the target table in `aiagent` if missing, then copy mappings from
--   `oasysbackup` using an upsert merge keyed by
--   `(hospital_id, policy_provider_id)`.
--
-- Behavior:
--   - Inserts missing mappings.
--   - Updates existing mappings' non-key payload columns.
--   - Preserves unrelated target rows.
--   - Preserves existing target row `id` on conflict.
--
-- Usage:
--   psql "postgresql://admin:admin123@localhost:5432/aiagent" \
--     -v ON_ERROR_STOP=1 \
--     -f scripts/copy_hospital_provider_mappings_to_aiagent.sql

BEGIN;

CREATE EXTENSION IF NOT EXISTS dblink;

CREATE TABLE IF NOT EXISTS public.hospital_provider_mappings (
    id UUID PRIMARY KEY,
    hospital_id UUID NOT NULL REFERENCES public.hospitals(id),
    policy_provider_id UUID NOT NULL REFERENCES public.policy_provider_configs(id),
    room_charges JSONB,
    extracted_data JSONB,
    mou_original_filename VARCHAR,
    mou_stored_filename VARCHAR,
    mou_file_path VARCHAR,
    mou_content_type VARCHAR,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_hospital_provider'
          AND conrelid = 'public.hospital_provider_mappings'::regclass
    ) THEN
        ALTER TABLE public.hospital_provider_mappings
            ADD CONSTRAINT uq_hospital_provider
            UNIQUE (hospital_id, policy_provider_id);
    END IF;
END $$;

CREATE TEMP TABLE tmp_source_hospital_provider_mappings AS
SELECT *
FROM dblink(
    'host=localhost port=5432 dbname=oasysbackup user=admin password=admin123',
    $sql$
    SELECT
        id,
        hospital_id,
        policy_provider_id,
        room_charges,
        extracted_data,
        mou_original_filename,
        mou_stored_filename,
        mou_file_path,
        mou_content_type,
        is_active,
        created_at,
        updated_at
    FROM public.hospital_provider_mappings
    $sql$
) AS src(
    id UUID,
    hospital_id UUID,
    policy_provider_id UUID,
    room_charges JSONB,
    extracted_data JSONB,
    mou_original_filename VARCHAR,
    mou_stored_filename VARCHAR,
    mou_file_path VARCHAR,
    mou_content_type VARCHAR,
    is_active BOOLEAN,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

DO $$
DECLARE
    missing_hospital_ids TEXT;
    missing_provider_ids TEXT;
BEGIN
    SELECT string_agg(src.hospital_id::text, ', ' ORDER BY src.hospital_id::text)
      INTO missing_hospital_ids
    FROM (
        SELECT DISTINCT hospital_id
        FROM tmp_source_hospital_provider_mappings
        EXCEPT
        SELECT id
        FROM public.hospitals
    ) AS src;

    IF missing_hospital_ids IS NOT NULL THEN
        RAISE EXCEPTION
            'Copy aborted: missing hospital_id(s) in aiagent.public.hospitals: %',
            missing_hospital_ids;
    END IF;

    SELECT string_agg(src.policy_provider_id::text, ', ' ORDER BY src.policy_provider_id::text)
      INTO missing_provider_ids
    FROM (
        SELECT DISTINCT policy_provider_id
        FROM tmp_source_hospital_provider_mappings
        EXCEPT
        SELECT id
        FROM public.policy_provider_configs
    ) AS src;

    IF missing_provider_ids IS NOT NULL THEN
        RAISE EXCEPTION
            'Copy aborted: missing policy_provider_id(s) in aiagent.public.policy_provider_configs: %',
            missing_provider_ids;
    END IF;
END $$;

INSERT INTO public.hospital_provider_mappings (
    id,
    hospital_id,
    policy_provider_id,
    room_charges,
    extracted_data,
    mou_original_filename,
    mou_stored_filename,
    mou_file_path,
    mou_content_type,
    is_active,
    created_at,
    updated_at
)
SELECT
    src.id,
    src.hospital_id,
    src.policy_provider_id,
    src.room_charges,
    src.extracted_data,
    src.mou_original_filename,
    src.mou_stored_filename,
    src.mou_file_path,
    src.mou_content_type,
    src.is_active,
    src.created_at,
    src.updated_at
FROM tmp_source_hospital_provider_mappings src
ON CONFLICT (hospital_id, policy_provider_id) DO UPDATE
SET room_charges = EXCLUDED.room_charges,
    extracted_data = EXCLUDED.extracted_data,
    mou_original_filename = EXCLUDED.mou_original_filename,
    mou_stored_filename = EXCLUDED.mou_stored_filename,
    mou_file_path = EXCLUDED.mou_file_path,
    mou_content_type = EXCLUDED.mou_content_type,
    is_active = EXCLUDED.is_active,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at;

COMMIT;
