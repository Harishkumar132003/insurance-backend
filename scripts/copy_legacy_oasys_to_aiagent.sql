-- Refresh the `aiagent` reporting snapshot from a LEGACY-schema `oasys` app DB.
--
-- Use this one for the production server (103.189.89.187), which is on an OLDER
-- schema than either the local `oasys` or `aiagent`. For a source already on the
-- new schema, use copy_oasys_to_aiagent.sql instead — it is a much simpler copy.
--
-- Full refresh: TRUNCATE + INSERT in one transaction, so it is idempotent, no
-- stale row survives a source delete, and any error rolls the whole thing back.
--
-- Usage — run AGAINST aiagent, with the SOURCE passed as :src.
--   psql "postgresql://admin:PASS@SERVER:5432/aiagent" -v ON_ERROR_STOP=1 \
--     -v src="host=SERVER port=5432 dbname=oasys user=admin password=PASS" \
--     -f scripts/copy_legacy_oasys_to_aiagent.sql
--
-- The source user needs SELECT on every source table. `oasys_ai_ro` is NOT
-- enough — it is denied on settlement_item and settlement_batch. Use admin.
--
--
-- WHAT THE LEGACY SOURCE IS MISSING, AND HOW EACH GAP IS FILLED
-- ------------------------------------------------------------
-- Five aiagent tables have no direct counterpart on the server:
--
--   patient_personal_detail   <- pre_auth_patient (table was renamed later)
--   preauth_status_tracking   <- status_history WHERE stage = 'PRE_AUTH'
--   claim_status_tracking     <- status_history WHERE stage = 'CLAIM'
--
-- `status_history` is the single pre-split log. It stores only the NEW status
-- per row, so `from_status` and `turn_around_time` are reconstructed with LAG
-- over (claim_case_id, created_at, id) — the same window the original
-- b1d4f7a2c9e3 / f3b7d2a9c5e8 migrations used for their backfill, so this
-- produces byte-identical tracking rows to a migrated DB.
--
-- Columns the source simply does not have, and their derivation:
--
--   pre_auth.preauth_raised_amount     <- pre_auth_stay.total_cost
--   pre_auth.preauth_approved_amount   <- hospitalization.approved_amount
--                                         (only for stage = 'PRE_AUTH' rows)
--   pre_auth.hospital_id               <- hospitalization.hospital_id
--   claims.uhid/claim_number/hospital_id            <- hospitalization
--   patient_personal_detail.hospitalization_id/uhid <- via pre_auth -> hospitalization
--   settlement_item.hospital_id/uhid                <- hospitalization
--   settlement_item.settlement_date    -> NULL (no source column; see
--                                         settlement_item_add_settlement_date_aiagent.sql)
--   settlement_batch.policy_provider_id-> NULL (no source column)
--
-- STATUS VOCABULARY: the cube models require claim-side statuses to be
-- CLAIM_-prefixed (cube/claim_status_tracking.yml), but the legacy server stores
-- them mixed — 'APPROVED' and 'CLAIM_ADR_SUBMITTED' both occur. Every claim-side
-- status is normalised to the prefixed form below. Pre-auth statuses are bare in
-- both, and are copied unchanged.
--
-- `format_tat` is created here because aiagent does not have it, and it must NOT
-- be called inside the remote query — the legacy server has no such function.
-- The interval crosses dblink raw and is rendered locally.

\if :{?src}
\else
\set src 'dbname=oasys'
\endif

\echo 'Refreshing aiagent from LEGACY source:' :src

CREATE EXTENSION IF NOT EXISTS dblink;

-- Render an interval as "1 day 2 min 20 sec", omitting zero components.
CREATE OR REPLACE FUNCTION public.format_tat(iv interval) RETURNS text
LANGUAGE sql IMMUTABLE AS $func$
    SELECT CASE WHEN iv IS NULL THEN NULL ELSE
        COALESCE(NULLIF(trim(concat_ws(' ',
            CASE WHEN EXTRACT(DAY    FROM iv)::int > 0
                 THEN EXTRACT(DAY FROM iv)::int || ' day' ||
                      CASE WHEN EXTRACT(DAY FROM iv)::int > 1 THEN 's' ELSE '' END END,
            CASE WHEN EXTRACT(HOUR   FROM iv)::int > 0 THEN EXTRACT(HOUR FROM iv)::int || ' hr' END,
            CASE WHEN EXTRACT(MINUTE FROM iv)::int > 0 THEN EXTRACT(MINUTE FROM iv)::int || ' min' END,
            CASE WHEN floor(EXTRACT(SECOND FROM iv))::int > 0
                 THEN floor(EXTRACT(SECOND FROM iv))::int || ' sec' END
        )), ''), '0 sec')
    END
$func$;

BEGIN;

TRUNCATE
  settlement_item, settlement_batch, claim_status_tracking, preauth_status_tracking,
  claims, patient_personal_detail, pre_auth, claim_case_emails,
  hospitalization, hospital_provider_mappings, policy_provider_configs, hospitals;

-- ---- 1. hospitals ----------------------------------------------------------
-- app_password is deliberately NULLed: a mailbox credential has no place in a
-- reporting DB, and no cube model exposes it.
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
-- case_status is copied verbatim. The legacy server already mixes bare and
-- CLAIM_-prefixed values there, which is what cube/hospitalization.yml documents.
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
-- Keeps the name `claim_case_id` in BOTH schemas — no alias needed here.
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

-- ---- 6. pre_auth  (+ the two amount columns the legacy schema lacks) --------
-- raised   <- pre_auth_stay.total_cost      (as migration d..0b3c7e4a9 backfilled it)
-- approved <- hospitalization.approved_amount, PRE_AUTH-stage rows only
INSERT INTO pre_auth (id, created_at, updated_at, hospitalization_id, preauth_status,
                      preauth_raised_amount, preauth_approved_amount, hospital_id)
SELECT * FROM dblink(:'src', $q$
  SELECT p.id, p.created_at, p.updated_at,
         p.claim_case_id AS hospitalization_id,
         p.preauth_status,
         s.total_cost    AS preauth_raised_amount,
         CASE WHEN p.stage = 'PRE_AUTH' THEN h.approved_amount END AS preauth_approved_amount,
         h.hospital_id
  FROM public.pre_auth p
  JOIN public.hospitalization h ON h.id = p.claim_case_id
  LEFT JOIN public.pre_auth_stay s ON s.form_data_id = p.id
$q$) AS t(id bigint, created_at timestamptz, updated_at timestamptz, hospitalization_id uuid,
          preauth_status varchar, preauth_raised_amount numeric(12,2),
          preauth_approved_amount numeric(12,2), hospital_id uuid);

-- ---- 7. patient_personal_detail  (source table: pre_auth_patient) ----------
INSERT INTO patient_personal_detail (id, form_data_id, patient_name, gender, address, age_years,
                                     occupation, employee_id, date_of_birth, policy_number,
                                     contact_number, corporate_name, insured_card_id,
                                     has_other_insurance, has_family_physician,
                                     family_physician_name, family_physician_contact,
                                     other_insurance_company, other_insurance_details,
                                     relative_contact_number, created_at, hospitalization_id, uhid)
SELECT * FROM dblink(:'src', $q$
  SELECT pp.id, pp.form_data_id, pp.patient_name, pp.gender, pp.address, pp.age_years,
         pp.occupation, pp.employee_id, pp.date_of_birth, pp.policy_number, pp.contact_number,
         pp.corporate_name, pp.insured_card_id, pp.has_other_insurance, pp.has_family_physician,
         pp.family_physician_name, pp.family_physician_contact, pp.other_insurance_company,
         pp.other_insurance_details, pp.relative_contact_number, pp.created_at,
         h.id AS hospitalization_id, h.uhid
  FROM public.pre_auth_patient pp
  JOIN public.pre_auth p ON p.id = pp.form_data_id
  JOIN public.hospitalization h ON h.id = p.claim_case_id
$q$) AS t(id bigint, form_data_id bigint, patient_name text, gender text, address text,
          age_years integer, occupation text, employee_id text, date_of_birth date,
          policy_number text, contact_number text, corporate_name text, insured_card_id text,
          has_other_insurance boolean, has_family_physician boolean, family_physician_name text,
          family_physician_contact text, other_insurance_company text,
          other_insurance_details text, relative_contact_number text, created_at timestamptz,
          hospitalization_id uuid, uhid varchar);

-- ---- 8. claims  (status normalised to the CLAIM_ vocabulary) ---------------
INSERT INTO claims (id, claimed_amount, approved_amount, status, submitted_at, processed_at,
                    created_at, hospitalization_id, uhid, claim_number, hospital_id)
SELECT * FROM dblink(:'src', $q$
  SELECT c.id, c.claimed_amount, c.approved_amount,
         CASE WHEN c.status LIKE 'CLAIM\_%' THEN c.status ELSE 'CLAIM_' || c.status END,
         c.submitted_at, c.processed_at, c.created_at,
         c.claim_case_id AS hospitalization_id,
         h.uhid, h.claim_number, h.hospital_id
  FROM public.claims c
  JOIN public.hospitalization h ON h.id = c.claim_case_id
$q$) AS t(id bigint, claimed_amount numeric(12,2), approved_amount numeric(12,2),
          status varchar, submitted_at timestamptz, processed_at timestamptz,
          created_at timestamptz, hospitalization_id uuid, uhid varchar, claim_number varchar,
          hospital_id uuid);

-- ---- 9. preauth_status_tracking  (from status_history, stage = PRE_AUTH) ---
-- LAG rebuilds from_status and TAT. The bare initial DRAFT row is excluded from
-- the output but still serves as the from_status of the SUBMITTED row, exactly
-- as migration b1d4f7a2c9e3's backfill did.
-- email_id is NULLed when it points at an email that no longer exists, so a
-- dangling reference cannot fail the FK.
INSERT INTO preauth_status_tracking (hospitalization_id, uhid, from_status, to_status,
                                     turn_around_time, turn_around_time_text, document_link,
                                     remark, created_at, email_id, hospital_id)
SELECT hospitalization_id, uhid, from_status, to_status, tat, public.format_tat(tat), docs,
       remark, created_at, email_id, hospital_id
FROM dblink(:'src', $q$
  SELECT * FROM (
    SELECT sh.claim_case_id AS hospitalization_id,
           h.uhid, h.hospital_id,
           LAG(sh.status) OVER w AS from_status,
           sh.status              AS to_status,
           sh.created_at - LAG(sh.created_at) OVER w AS tat,
           (SELECT jsonb_agg(a.file_path ORDER BY a.id)
              FROM public.claim_case_email_attachments a WHERE a.email_id = sh.email_id) AS docs,
           sh.remarks AS remark,
           sh.created_at,
           (SELECT e.id FROM public.claim_case_emails e WHERE e.id = sh.email_id) AS email_id
    FROM public.status_history sh
    JOIN public.hospitalization h ON h.id = sh.claim_case_id
    WHERE sh.stage = 'PRE_AUTH'
    WINDOW w AS (PARTITION BY sh.claim_case_id ORDER BY sh.created_at, sh.id)
  ) t WHERE t.to_status <> 'DRAFT'
$q$) AS t(hospitalization_id uuid, uhid varchar, hospital_id uuid, from_status varchar,
          to_status varchar, tat interval, docs jsonb, remark text, created_at timestamptz,
          email_id bigint);

-- ---- 10. claim_status_tracking  (from status_history, stage = CLAIM) -------
-- Both from_status and to_status get the CLAIM_ prefix, and the LAG runs over the
-- ALREADY-normalised value so a transition never mixes vocabularies.
INSERT INTO claim_status_tracking (hospitalization_id, uhid, claim_number, from_status,
                                   to_status, turn_around_time, turn_around_time_text,
                                   document_link, remark, created_at, email_id, hospital_id)
SELECT hospitalization_id, uhid, claim_number, from_status, to_status, tat,
       public.format_tat(tat), docs, remark, created_at, email_id, hospital_id
FROM dblink(:'src', $q$
  SELECT sh.claim_case_id AS hospitalization_id,
         h.uhid, h.claim_number, h.hospital_id,
         LAG(CASE WHEN sh.status LIKE 'CLAIM\_%' THEN sh.status
                  ELSE 'CLAIM_' || sh.status END) OVER w AS from_status,
         CASE WHEN sh.status LIKE 'CLAIM\_%' THEN sh.status
              ELSE 'CLAIM_' || sh.status END AS to_status,
         sh.created_at - LAG(sh.created_at) OVER w AS tat,
         (SELECT jsonb_agg(fp ORDER BY fp) FROM (
             SELECT DISTINCT ON (original_filename) file_path AS fp FROM (
                 SELECT a.original_filename, a.file_path, 1 AS pref
                   FROM public.claim_case_email_attachments a WHERE a.email_id = sh.email_id
                 UNION ALL
                 SELECT d.original_filename, d.file_path, 2 AS pref
                   FROM public.claim_case_documents d WHERE d.sent_email_id = sh.email_id
             ) u ORDER BY original_filename, pref
         ) y) AS docs,
         sh.remarks AS remark,
         sh.created_at,
         (SELECT e.id FROM public.claim_case_emails e WHERE e.id = sh.email_id) AS email_id
  FROM public.status_history sh
  JOIN public.hospitalization h ON h.id = sh.claim_case_id
  WHERE sh.stage = 'CLAIM'
  WINDOW w AS (PARTITION BY sh.claim_case_id ORDER BY sh.created_at, sh.id)
$q$) AS t(hospitalization_id uuid, uhid varchar, claim_number varchar, hospital_id uuid,
          from_status varchar, to_status varchar, tat interval, docs jsonb, remark text,
          created_at timestamptz, email_id bigint);

-- ---- 11. settlement_batch  (policy_provider_id absent upstream) ------------
INSERT INTO settlement_batch (id, hospital_id, tpa_insurer, total_settlement_amount,
                              payment_mode, payment_batch, utr_number, settlement_number,
                              settlement_date, hospital_account_number, source_original_filename,
                              source_stored_filename, source_file_path, source_content_type,
                              created_at, updated_at, policy_provider_id)
SELECT id, hospital_id, tpa_insurer, total_settlement_amount, payment_mode, payment_batch,
       utr_number, settlement_number, settlement_date, hospital_account_number,
       source_original_filename, source_stored_filename, source_file_path, source_content_type,
       created_at, updated_at, NULL
FROM dblink(:'src', $q$
  SELECT id, hospital_id, tpa_insurer, total_settlement_amount, payment_mode, payment_batch,
         utr_number, settlement_number, settlement_date, hospital_account_number,
         source_original_filename, source_stored_filename, source_file_path,
         source_content_type, created_at, updated_at
  FROM public.settlement_batch
$q$) AS t(id uuid, hospital_id uuid, tpa_insurer varchar, total_settlement_amount numeric(14,2),
          payment_mode varchar, payment_batch varchar, utr_number varchar,
          settlement_number varchar, settlement_date date, hospital_account_number varchar,
          source_original_filename varchar, source_stored_filename varchar,
          source_file_path varchar, source_content_type varchar, created_at timestamptz,
          updated_at timestamptz);

-- ---- 12. settlement_item ---------------------------------------------------
-- settlement_date has no source column; backfill afterwards with
-- settlement_item_add_settlement_date_aiagent.sql if you need item-level dates.
INSERT INTO settlement_item (id, batch_id, claim_number, settled_amount, claim_raised_amount,
                             disallowance, disallowance_reason, hospitalization_id, is_matched,
                             created_at, hospital_id, uhid, settlement_date)
SELECT id, batch_id, claim_number, settled_amount, claim_raised_amount, disallowance,
       disallowance_reason, hospitalization_id, is_matched, created_at, hospital_id, uhid, NULL
FROM dblink(:'src', $q$
  SELECT si.id, si.batch_id, si.claim_number, si.settled_amount, si.claim_raised_amount,
         si.disallowance, si.disallowance_reason,
         si.claim_case_id AS hospitalization_id, si.is_matched, si.created_at,
         h.hospital_id, h.uhid
  FROM public.settlement_item si
  JOIN public.hospitalization h ON h.id = si.claim_case_id
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
UNION ALL SELECT 'claim_case_emails', count(*) FROM claim_case_emails
UNION ALL SELECT 'pre_auth', count(*) FROM pre_auth
UNION ALL SELECT 'patient_personal_detail', count(*) FROM patient_personal_detail
UNION ALL SELECT 'claims', count(*) FROM claims
UNION ALL SELECT 'preauth_status_tracking', count(*) FROM preauth_status_tracking
UNION ALL SELECT 'claim_status_tracking', count(*) FROM claim_status_tracking
UNION ALL SELECT 'settlement_batch', count(*) FROM settlement_batch
UNION ALL SELECT 'settlement_item', count(*) FROM settlement_item
ORDER BY 1;
