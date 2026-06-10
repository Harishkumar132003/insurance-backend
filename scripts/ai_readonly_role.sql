-- =====================================================================
-- OASYS AI Query Agent — read-only role + Row-Level Security (RLS)
-- =====================================================================
-- This is the SAFETY CORE for the natural-language query agent. The agent
-- generates arbitrary SELECT SQL, so we do NOT trust the prompt for either
-- write-protection or tenant isolation. Both are enforced by Postgres:
--
--   1. WRITE PROTECTION — a dedicated login role (`oasys_ai_ro`) that is
--      granted SELECT only, on a curated set of tables. It physically cannot
--      INSERT / UPDATE / DELETE / run DDL.
--
--   2. TENANT ISOLATION — RLS policies scoped TO oasys_ai_ro filter every row
--      to the caller's hospital, read from the per-connection GUC
--      `oasys.hospital_id`. The backend sets this GUC for each request
--      (see app/db/readonly_session.py). If the GUC is unset/empty the
--      policies match NO rows (fail-closed).
--
-- RLS is ENABLED (not FORCED) so the table owner / superuser the main app
-- connects as is unaffected — only the non-owner `oasys_ai_ro` role is
-- filtered. Policies are scoped `TO oasys_ai_ro` for the same reason.
--
-- Run as a superuser / table owner, once per environment:
--   psql "$DATABASE_URL" -v ai_ro_password="'choose-a-strong-password'" \
--        -f scripts/ai_readonly_role.sql
-- Re-running is safe (idempotent).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Login role
-- ---------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oasys_ai_ro') THEN
    EXECUTE format('CREATE ROLE oasys_ai_ro LOGIN PASSWORD %L', :ai_ro_password);
  ELSE
    EXECUTE format('ALTER ROLE oasys_ai_ro PASSWORD %L', :ai_ro_password);
  END IF;
END $$;

-- Belt-and-braces: this role can only ever read.
ALTER ROLE oasys_ai_ro SET default_transaction_read_only = on;
-- Bound any single statement so a heavy generated query can't pin the DB.
ALTER ROLE oasys_ai_ro SET statement_timeout = '15s';
ALTER ROLE oasys_ai_ro SET idle_in_transaction_session_timeout = '15s';

DO $$
BEGIN
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM oasys_ai_ro', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO oasys_ai_ro', current_database());
END $$;
GRANT USAGE ON SCHEMA public TO oasys_ai_ro;

-- Make sure no blanket grants linger from a previous run.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM oasys_ai_ro;

-- ---------------------------------------------------------------------
-- 2. SELECT grants — ONLY the tables the agent is allowed to see.
--    `patients` and `alembic_version` are intentionally excluded:
--    `patients` has no tenant column (would leak across hospitals), and
--    patient data is still reachable, tenant-scoped, via pre_auth_patient.
-- ---------------------------------------------------------------------
DO $$
DECLARE
  allowed text[] := ARRAY[
    -- tenant-owned (RLS applied below)
    'hospitals','users','hospitalization','cc_emails','execution_logs',
    'hospital_configs','hospital_prompts','hospital_provider_mappings',
    'pre_auth','pre_auth_patient','pre_auth_stay','pre_auth_treatment',
    'claims','settlements','invoice','invoice_payment','status_history',
    'query_logs','claim_case_emails','claim_case_email_attachments',
    'claim_case_documents','part_d_letters','claim_bill_item',
    -- shared reference data (no RLS — non-sensitive, needed for labels/joins)
    'policy_provider_configs','form_templates','email_templates',
    'summary_prompt_templates','features'
  ];
  t text;
BEGIN
  FOREACH t IN ARRAY allowed LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables
              WHERE table_schema='public' AND table_name=t) THEN
      EXECUTE format('GRANT SELECT ON public.%I TO oasys_ai_ro', t);
    END IF;
  END LOOP;
END $$;

-- ---------------------------------------------------------------------
-- 3. Tenant key helper — the current hospital from the per-connection GUC.
--    Returns NULL when unset/empty so every RLS policy below matches no
--    rows (fail-closed) until the backend sets oasys.hospital_id.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.oasys_current_hospital()
RETURNS uuid
LANGUAGE sql STABLE
AS $$ SELECT nullif(current_setting('oasys.hospital_id', true), '')::uuid $$;

-- ---------------------------------------------------------------------
-- 4. RLS policies. Helper applies ENABLE RLS + a SELECT policy scoped to
--    oasys_ai_ro with the given USING predicate.
-- ---------------------------------------------------------------------
DO $$
DECLARE
  rec record;
  -- table  =>  row-visibility predicate (the row is visible iff true)
  -- Tier 0: direct hospital_id
  direct text[] := ARRAY[
    'hospitalization','users','cc_emails','execution_logs',
    'hospital_configs','hospital_prompts','hospital_provider_mappings'
  ];
  -- Tier 1: claim_case_id -> hospitalization.hospital_id
  via_case text[] := ARRAY[
    'pre_auth','claims','status_history','query_logs','claim_case_emails',
    'claim_case_email_attachments','claim_case_documents','part_d_letters','invoice'
  ];
  -- Tier 2: form_data_id -> pre_auth -> hospitalization
  via_form text[] := ARRAY[
    'claim_bill_item','pre_auth_patient','pre_auth_stay','pre_auth_treatment'
  ];
  t text;
  pred text;
BEGIN
  -- hospitals: the row IS the hospital
  EXECUTE 'ALTER TABLE public.hospitals ENABLE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS ai_ro_tenant ON public.hospitals';
  EXECUTE 'CREATE POLICY ai_ro_tenant ON public.hospitals FOR SELECT TO oasys_ai_ro
           USING (id = public.oasys_current_hospital())';

  FOREACH t IN ARRAY direct LOOP
    pred := 'hospital_id = public.oasys_current_hospital()';
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS ai_ro_tenant ON public.%I', t);
    EXECUTE format('CREATE POLICY ai_ro_tenant ON public.%I FOR SELECT TO oasys_ai_ro USING (%s)', t, pred);
  END LOOP;

  FOREACH t IN ARRAY via_case LOOP
    pred := 'claim_case_id IN (SELECT id FROM public.hospitalization WHERE hospital_id = public.oasys_current_hospital())';
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS ai_ro_tenant ON public.%I', t);
    EXECUTE format('CREATE POLICY ai_ro_tenant ON public.%I FOR SELECT TO oasys_ai_ro USING (%s)', t, pred);
  END LOOP;

  FOREACH t IN ARRAY via_form LOOP
    pred := 'form_data_id IN (SELECT pa.id FROM public.pre_auth pa JOIN public.hospitalization h ON h.id = pa.claim_case_id WHERE h.hospital_id = public.oasys_current_hospital())';
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS ai_ro_tenant ON public.%I', t);
    EXECUTE format('CREATE POLICY ai_ro_tenant ON public.%I FOR SELECT TO oasys_ai_ro USING (%s)', t, pred);
  END LOOP;

  -- Tier 3: deeper chains
  -- settlements -> claims.claim_case_id -> hospitalization
  EXECUTE 'ALTER TABLE public.settlements ENABLE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS ai_ro_tenant ON public.settlements';
  EXECUTE 'CREATE POLICY ai_ro_tenant ON public.settlements FOR SELECT TO oasys_ai_ro
           USING (claim_id IN (SELECT c.id FROM public.claims c
                               JOIN public.hospitalization h ON h.id = c.claim_case_id
                               WHERE h.hospital_id = public.oasys_current_hospital()))';

  -- invoice_payment -> invoice.claim_case_id -> hospitalization
  EXECUTE 'ALTER TABLE public.invoice_payment ENABLE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS ai_ro_tenant ON public.invoice_payment';
  EXECUTE 'CREATE POLICY ai_ro_tenant ON public.invoice_payment FOR SELECT TO oasys_ai_ro
           USING (invoice_id IN (SELECT i.id FROM public.invoice i
                                 JOIN public.hospitalization h ON h.id = i.claim_case_id
                                 WHERE h.hospital_id = public.oasys_current_hospital()))';
END $$;

-- ---------------------------------------------------------------------
-- 5. Quick verification (optional — prints what the role can see)
-- ---------------------------------------------------------------------
-- SELECT table_name, privilege_type
--   FROM information_schema.role_table_grants
--  WHERE grantee = 'oasys_ai_ro' ORDER BY table_name;
