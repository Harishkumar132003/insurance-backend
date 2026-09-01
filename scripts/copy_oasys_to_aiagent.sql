-- Refresh the `aiagent` reporting snapshot from the live `oasys` app DB.
--
-- `aiagent` is the read-only DB that Cube (and therefore /ai/intent and /ai2/*)
-- queries. It is a SNAPSHOT, not a live mirror: run this whenever you want the
-- AI to see current data.
--
-- Full refresh by design — TRUNCATE + INSERT inside one transaction. That makes
-- it idempotent with no upsert bookkeeping, and no stale row can survive a
-- source delete. Any failure rolls the whole thing back, so a half-copied
-- snapshot is impossible.
--
-- Usage (inside the container, both DBs local to it):
--   docker exec -i oasys-postgres psql -U admin -d aiagent -v ON_ERROR_STOP=1 \
--     < scripts/copy_oasys_to_aiagent.sql
--
-- Usage (remote source, e.g. from your laptop against the server):
--   psql "postgresql://admin:PASS@HOST:5432/aiagent" -v ON_ERROR_STOP=1 \
--     -v src="host=HOST port=5432 dbname=oasys user=admin password=PASS" \
--     -f scripts/copy_oasys_to_aiagent.sql
--
-- SCHEMA NOTE — why three tables need a column alias:
--   `oasys` sits at alembic c5e9a2b6d3f8, before the three
--   rename_*_claim_case_id migrations that head (c6e0f4a8b2d5) applies. So the
--   source still calls the case FK `claim_case_id` where `aiagent` calls it
--   `hospitalization_id`. Same uuid values — only the name differs, and
--   `SELECT claim_case_id AS hospitalization_id` bridges it. Running those
--   migrations on the app DB is NOT required for this copy.
--   The other 9 tables are column-identical.
--
-- The 3 views (revenue_lifecycle, preauth_operations, claims_operations) read
-- these tables, so they pick up new data automatically. Nothing to do for them.

\if :{?src}
\else
\set src 'dbname=oasys'
\endif

\echo 'Refreshing aiagent from:' :src

CREATE EXTENSION IF NOT EXISTS dblink;

BEGIN;

-- One statement so Postgres resolves FK order itself; every referenced table is
-- in the list, so no CASCADE is needed and nothing outside these 12 is touched.
TRUNCATE
  settlement_item, settlement_batch, claim_case_emails,
  claim_status_tracking, preauth_status_tracking,
  claims, pre_auth, patient_personal_detail,
  hospitalization, hospital_provider_mappings,
  policy_provider_configs, hospitals;

-- ---- 1. hospitals ----------------------------------------------------------
-- app_password is deliberately NULLed: it is a mailbox credential, no cube model
-- exposes it, and a reporting DB is the wrong place for a secret.
INSERT INTO hospitals (id, name, created_at, updated_at, address, rohini_id, email, app_password)
SELECT id, name, created_at, updated_at, address, rohini_id, email, NULL
FROM dblink(:'src', $q$
  SELECT id, name, created_at, updated_at, address, rohini_id, email FROM public.hospitals
$q$) AS t(id uuid, name varchar, created_at timestamptz, updated_at timestamptz,
          address varchar, rohini_id varchar, email varchar);

-- ---- 2. policy_provider_configs --------------------------------------------
INSERT INTO policy_provider_configs (id, name, config, created_at, updated_at, provider_id,
                                     email, tpa_name, tpa_toll_free_phone, tpa_toll_free_fax,
                                     is_onboarded)
SELECT * FROM dblink(:'src', $q$
  SELECT id, name, config, created_at, updated_at, provider_id, email, tpa_name,
         tpa_toll_free_phone, tpa_toll_free_fax, is_onboarded
  FROM public.policy_provider_configs
$q$) AS t(id uuid, name varchar, config jsonb, created_at timestamptz, updated_at timestamptz,
          provider_id varchar, email varchar, tpa_name varchar, tpa_toll_free_phone varchar,
          tpa_toll_free_fax varchar, is_onboarded boolean);

-- ---- 3. hospital_provider_mappings -----------------------------------------
INSERT INTO hospital_provider_mappings (id, hospital_id, policy_provider_id, room_charges,
                                        extracted_data, mou_original_filename,
                                        mou_stored_filename, mou_file_path, mou_content_type,
                                        is_active, created_at, updated_at)
SELECT * FROM dblink(:'src', $q$
  SELECT id, hospital_id, policy_provider_id, room_charges, extracted_data,
         mou_original_filename, mou_stored_filename, mou_file_path, mou_content_type,
         is_active, created_at, updated_at
  FROM public.hospital_provider_mappings
$q$) AS t(id uuid, hospital_id uuid, policy_provider_id uuid, room_charges jsonb,
          extracted_data jsonb, mou_original_filename varchar, mou_stored_filename varchar,
          mou_file_path varchar, mou_content_type varchar, is_active boolean,
          created_at timestamptz, updated_at timestamptz);

-- ---- 4. hospitalization ----------------------------------------------------
INSERT INTO hospitalization (id, hospital_id, policy_provider_id, case_status, created_at,
                             updated_at, uhid, claim_number, current_stage, preauth_outcome,
                             thread_id, approved_amount)
SELECT * FROM dblink(:'src', $q$
  SELECT id, hospital_id, policy_provider_id, case_status, created_at, updated_at, uhid,
         claim_number, current_stage, preauth_outcome, thread_id, approved_amount
  FROM public.hospitalization
$q$) AS t(id uuid, hospital_id uuid, policy_provider_id uuid, case_status varchar,
          created_at timestamptz, updated_at timestamptz, uhid varchar, claim_number varchar,
          current_stage varchar, preauth_outcome varchar, thread_id varchar,
          approved_amount numeric(12,2));

-- ---- 5. claim_case_emails --------------------------------------------------
-- Keeps its own `claim_case_id` name in BOTH databases — no alias here.
INSERT INTO claim_case_emails (id, direction, from_email, to_email, subject, body, message_id,
                               thread_id, email_date, created_at, email_type, claim_case_id,
                               is_read, ai_suggested_status, ai_suggested_amount,
                               ai_suggested_claim_number, ai_summary, ai_query_details,
                               ai_documents_requested, validation_status, validated_at,
                               validated_by, provider_read, ai_documents_list, form_values,
                               ai_approved_breakdown, ai_denial_reason)
SELECT * FROM dblink(:'src', $q$
  SELECT id, direction, from_email, to_email, subject, body, message_id, thread_id, email_date,
         created_at, email_type, claim_case_id, is_read, ai_suggested_status,
         ai_suggested_amount, ai_suggested_claim_number, ai_summary, ai_query_details,
         ai_documents_requested, validation_status, validated_at, validated_by, provider_read,
         ai_documents_list, form_values, ai_approved_breakdown, ai_denial_reason
  FROM public.claim_case_emails
$q$) AS t(id bigint, direction varchar, from_email varchar, to_email varchar, subject varchar,
          body text, message_id varchar, thread_id varchar, email_date timestamptz,
          created_at timestamptz, email_type varchar, claim_case_id uuid, is_read boolean,
          ai_suggested_status varchar, ai_suggested_amount numeric(12,2),
          ai_suggested_claim_number varchar, ai_summary text, ai_query_details text,
          ai_documents_requested text, validation_status varchar, validated_at timestamptz,
          validated_by uuid, provider_read boolean, ai_documents_list jsonb, form_values jsonb,
          ai_approved_breakdown jsonb, ai_denial_reason text);

-- ---- 6. pre_auth  (claim_case_id -> hospitalization_id) --------------------
-- Source also carries claimed_amount / draft_state / remarks / stage; aiagent has
-- no such columns and no cube model reads them, so they are not copied.
INSERT INTO pre_auth (id, created_at, updated_at, hospitalization_id, preauth_status,
                      preauth_raised_amount, preauth_approved_amount, hospital_id)
SELECT * FROM dblink(:'src', $q$
  SELECT id, created_at, updated_at, claim_case_id AS hospitalization_id, preauth_status,
         preauth_raised_amount, preauth_approved_amount, hospital_id
  FROM public.pre_auth
$q$) AS t(id bigint, created_at timestamptz, updated_at timestamptz, hospitalization_id uuid,
          preauth_status varchar, preauth_raised_amount numeric(12,2),
          preauth_approved_amount numeric(12,2), hospital_id uuid);

-- ---- 7. patient_personal_detail --------------------------------------------
INSERT INTO patient_personal_detail (id, form_data_id, patient_name, gender, address, age_years,
                                     occupation, employee_id, date_of_birth, policy_number,
                                     contact_number, corporate_name, insured_card_id,
                                     has_other_insurance, has_family_physician,
                                     family_physician_name, family_physician_contact,
                                     other_insurance_company, other_insurance_details,
                                     relative_contact_number, created_at, hospitalization_id, uhid)
SELECT * FROM dblink(:'src', $q$
  SELECT id, form_data_id, patient_name, gender, address, age_years, occupation, employee_id,
         date_of_birth, policy_number, contact_number, corporate_name, insured_card_id,
         has_other_insurance, has_family_physician, family_physician_name,
         family_physician_contact, other_insurance_company, other_insurance_details,
         relative_contact_number, created_at, hospitalization_id, uhid
  FROM public.patient_personal_detail
$q$) AS t(id bigint, form_data_id bigint, patient_name text, gender text, address text,
          age_years integer, occupation text, employee_id text, date_of_birth date,
          policy_number text, contact_number text, corporate_name text, insured_card_id text,
          has_other_insurance boolean, has_family_physician boolean, family_physician_name text,
          family_physician_contact text, other_insurance_company text,
          other_insurance_details text, relative_contact_number text, created_at timestamptz,
          hospitalization_id uuid, uhid varchar);

-- ---- 8. claims  (claim_case_id -> hospitalization_id) ----------------------
INSERT INTO claims (id, claimed_amount, approved_amount, status, submitted_at, processed_at,
                    created_at, hospitalization_id, uhid, claim_number, hospital_id)
SELECT * FROM dblink(:'src', $q$
  SELECT id, claimed_amount, approved_amount, status, submitted_at, processed_at, created_at,
         claim_case_id AS hospitalization_id, uhid, claim_number, hospital_id
  FROM public.claims
$q$) AS t(id bigint, claimed_amount numeric(12,2), approved_amount numeric(12,2),
          status varchar, submitted_at timestamptz, processed_at timestamptz,
          created_at timestamptz, hospitalization_id uuid, uhid varchar, claim_number varchar,
          hospital_id uuid);

-- ---- 9. preauth_status_tracking --------------------------------------------
INSERT INTO preauth_status_tracking (id, hospitalization_id, uhid, from_status, to_status,
                                     turn_around_time, document_link, remark, created_at,
                                     turn_around_time_text, email_id, hospital_id)
SELECT * FROM dblink(:'src', $q$
  SELECT id, hospitalization_id, uhid, from_status, to_status, turn_around_time, document_link,
         remark, created_at, turn_around_time_text, email_id, hospital_id
  FROM public.preauth_status_tracking
$q$) AS t(id bigint, hospitalization_id uuid, uhid varchar, from_status varchar,
          to_status varchar, turn_around_time interval, document_link jsonb, remark text,
          created_at timestamptz, turn_around_time_text varchar, email_id bigint,
          hospital_id uuid);

-- ---- 10. claim_status_tracking ---------------------------------------------
INSERT INTO claim_status_tracking (id, hospitalization_id, uhid, claim_number, email_id,
                                   from_status, to_status, turn_around_time,
                                   turn_around_time_text, document_link, remark, created_at,
                                   hospital_id)
SELECT * FROM dblink(:'src', $q$
  SELECT id, hospitalization_id, uhid, claim_number, email_id, from_status, to_status,
         turn_around_time, turn_around_time_text, document_link, remark, created_at, hospital_id
  FROM public.claim_status_tracking
$q$) AS t(id bigint, hospitalization_id uuid, uhid varchar, claim_number varchar,
          email_id bigint, from_status varchar, to_status varchar, turn_around_time interval,
          turn_around_time_text varchar, document_link jsonb, remark text,
          created_at timestamptz, hospital_id uuid);

-- ---- 11. settlement_batch --------------------------------------------------
INSERT INTO settlement_batch (id, hospital_id, tpa_insurer, total_settlement_amount,
                              payment_mode, payment_batch, utr_number, settlement_number,
                              settlement_date, hospital_account_number, source_original_filename,
                              source_stored_filename, source_file_path, source_content_type,
                              created_at, updated_at, policy_provider_id)
SELECT * FROM dblink(:'src', $q$
  SELECT id, hospital_id, tpa_insurer, total_settlement_amount, payment_mode, payment_batch,
         utr_number, settlement_number, settlement_date, hospital_account_number,
         source_original_filename, source_stored_filename, source_file_path,
         source_content_type, created_at, updated_at, policy_provider_id
  FROM public.settlement_batch
$q$) AS t(id uuid, hospital_id uuid, tpa_insurer varchar, total_settlement_amount numeric(14,2),
          payment_mode varchar, payment_batch varchar, utr_number varchar,
          settlement_number varchar, settlement_date date, hospital_account_number varchar,
          source_original_filename varchar, source_stored_filename varchar,
          source_file_path varchar, source_content_type varchar, created_at timestamptz,
          updated_at timestamptz, policy_provider_id uuid);

-- ---- 12. settlement_item  (claim_case_id -> hospitalization_id) ------------
-- `settlement_date` exists only in aiagent — the source has no such column, so it
-- lands NULL. Backfill it afterwards with
-- scripts/settlement_item_add_settlement_date_aiagent.sql, or leave NULL if you
-- do not query settlement dates at item level.
INSERT INTO settlement_item (id, batch_id, claim_number, settled_amount, claim_raised_amount,
                             disallowance, disallowance_reason, hospitalization_id, is_matched,
                             created_at, hospital_id, uhid, settlement_date)
SELECT id, batch_id, claim_number, settled_amount, claim_raised_amount, disallowance,
       disallowance_reason, hospitalization_id, is_matched, created_at, hospital_id, uhid, NULL
FROM dblink(:'src', $q$
  SELECT id, batch_id, claim_number, settled_amount, claim_raised_amount, disallowance,
         disallowance_reason, claim_case_id AS hospitalization_id, is_matched, created_at,
         hospital_id, uhid
  FROM public.settlement_item
$q$) AS t(id bigint, batch_id uuid, claim_number varchar, settled_amount numeric(14,2),
          claim_raised_amount numeric(14,2), disallowance numeric(14,2),
          disallowance_reason varchar, hospitalization_id uuid, is_matched boolean,
          created_at timestamptz, hospital_id uuid, uhid varchar);
COMMIT;

-- Row counts, so a run that silently copied nothing is visible immediately.
SELECT 'hospitals' AS table_name, count(*) FROM hospitals
UNION ALL SELECT 'policy_provider_configs', count(*) FROM policy_provider_configs
UNION ALL SELECT 'hospital_provider_mappings', count(*) FROM hospital_provider_mappings
UNION ALL SELECT 'hospitalization', count(*) FROM hospitalization
UNION ALL SELECT 'patient_personal_detail', count(*) FROM patient_personal_detail
UNION ALL SELECT 'pre_auth', count(*) FROM pre_auth
UNION ALL SELECT 'claims', count(*) FROM claims
UNION ALL SELECT 'preauth_status_tracking', count(*) FROM preauth_status_tracking
UNION ALL SELECT 'claim_status_tracking', count(*) FROM claim_status_tracking
UNION ALL SELECT 'claim_case_emails', count(*) FROM claim_case_emails
UNION ALL SELECT 'settlement_batch', count(*) FROM settlement_batch
UNION ALL SELECT 'settlement_item', count(*) FROM settlement_item
ORDER BY 1;
