-- One-shot in-place migration: bring a target DB from the OLD schema
-- (claim_cases / form_data with data_json / pre_auths) to the NEW schema
-- (hospitalization / pre_auth + typed children / claim_bill_item, no data_json),
-- preserving ALL existing data via JSON-extraction backfills.
--
-- Usage:
--   PGPASSWORD=... psql -h <host> -U admin -d oasys -v ON_ERROR_STOP=1 \
--     -f scripts/migrate_data.sql
--
-- Idempotent: a re-run on a partially- or fully-migrated DB is safe (guarded
-- on table/column existence). Runs as a single transaction; any error rolls
-- back the entire migration.

BEGIN;

-- ────────────────────────────────────────────────────────────────────
-- 1. Drop the dead pre_auths table (never populated; idempotent).
-- ────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS pre_auths;

-- ────────────────────────────────────────────────────────────────────
-- 2. Rename hub + form tables (guarded so reruns don't fail).
--    Child FKs auto-follow the rename (Postgres references parent by OID).
-- ────────────────────────────────────────────────────────────────────
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='claim_cases') THEN
    ALTER TABLE claim_cases RENAME TO hospitalization;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='form_data') THEN
    ALTER TABLE form_data RENAME TO pre_auth;
  END IF;
END $$;

-- ────────────────────────────────────────────────────────────────────
-- 3. Add the new pre_auth columns (stage discriminator + claim-stage fields).
-- ────────────────────────────────────────────────────────────────────
ALTER TABLE pre_auth ADD COLUMN IF NOT EXISTS stage VARCHAR NOT NULL DEFAULT 'PRE_AUTH';
ALTER TABLE pre_auth ADD COLUMN IF NOT EXISTS claimed_amount NUMERIC(12,2);
ALTER TABLE pre_auth ADD COLUMN IF NOT EXISTS remarks TEXT;

-- ────────────────────────────────────────────────────────────────────
-- 4. Create the typed pre-auth section tables (1:1 with pre_auth).
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pre_auth_patient (
    id BIGSERIAL PRIMARY KEY,
    form_data_id BIGINT NOT NULL UNIQUE REFERENCES pre_auth(id) ON DELETE CASCADE,
    patient_name TEXT, gender TEXT, address TEXT, age_years INTEGER, occupation TEXT,
    employee_id TEXT, date_of_birth DATE, policy_number TEXT, contact_number TEXT,
    corporate_name TEXT, insured_card_id TEXT,
    has_other_insurance BOOLEAN, has_family_physician BOOLEAN,
    family_physician_name TEXT, family_physician_contact TEXT,
    other_insurance_company TEXT, other_insurance_details TEXT, relative_contact_number TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pre_auth_patient_form_data_id ON pre_auth_patient(form_data_id);

CREATE TABLE IF NOT EXISTS pre_auth_treatment (
    id BIGSERIAL PRIMARY KEY,
    form_data_id BIGINT NOT NULL UNIQUE REFERENCES pre_auth(id) ON DELETE CASCADE,
    doctor_name TEXT, provisional_diagnosis TEXT, icd10_code TEXT, surgery_name TEXT,
    surgery_icd_code TEXT, drug_route TEXT, injury_cause TEXT, past_history TEXT,
    duration_days INTEGER, other_treatment TEXT, critical_findings TEXT,
    treatment_details TEXT, illness_description TEXT, first_consultation_date DATE,
    tp_investigation BOOLEAN, tp_intensive_care BOOLEAN, tp_non_allopathic BOOLEAN,
    tp_medical_management BOOLEAN, tp_surgical_management BOOLEAN,
    ad_is_rta BOOLEAN, ad_substance_abuse BOOLEAN, ad_reported_to_police BOOLEAN, ad_test_conducted TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pre_auth_treatment_form_data_id ON pre_auth_treatment(form_data_id);

CREATE TABLE IF NOT EXISTS pre_auth_stay (
    id BIGSERIAL PRIMARY KEY,
    form_data_id BIGINT NOT NULL UNIQUE REFERENCES pre_auth(id) ON DELETE CASCADE,
    room_type TEXT, is_emergency BOOLEAN, icu_days INTEGER, expected_days INTEGER,
    admission_date DATE, admission_time TEXT,
    room_rent NUMERIC(12,2), ot_charges NUMERIC(12,2), icu_charges NUMERIC(12,2),
    medicines_cost NUMERIC(12,2), investigation_cost NUMERIC(12,2),
    professional_fees NUMERIC(12,2), package_charges NUMERIC(12,2),
    other_expenses NUMERIC(12,2), total_cost NUMERIC(12,2),
    cc_diabetes BOOLEAN, cc_hypertension BOOLEAN, cc_heart_disease BOOLEAN,
    cc_asthma_copd BOOLEAN, cc_cancer BOOLEAN, cc_hiv_std BOOLEAN,
    cc_hyperlipidemia BOOLEAN, cc_osteoarthritis BOOLEAN, cc_alcohol_drug_abuse BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pre_auth_stay_form_data_id ON pre_auth_stay(form_data_id);

-- ────────────────────────────────────────────────────────────────────
-- 5. Claim-stage bill-breakdown lines.
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS claim_bill_item (
    id BIGSERIAL PRIMARY KEY,
    form_data_id BIGINT NOT NULL REFERENCES pre_auth(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_claim_bill_item_form_data_id ON claim_bill_item(form_data_id);

-- ────────────────────────────────────────────────────────────────────
-- 6. DATA MIGRATION from data_json (skipped if column already dropped).
--    Wrapped in plpgsql so the entire block is a no-op on a rerun.
-- ────────────────────────────────────────────────────────────────────
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='pre_auth' AND column_name='data_json'
  ) THEN
    RAISE NOTICE 'data_json column already dropped — skipping backfill';
    RETURN;
  END IF;

  -- 6a. Set the stage discriminator from data_json.
  UPDATE pre_auth SET stage = 'CLAIM' WHERE data_json->>'stage' = 'CLAIM';
  UPDATE pre_auth SET stage = 'PRE_AUTH' WHERE (data_json->>'stage') IS DISTINCT FROM 'CLAIM';

  -- 6b. Backfill claim-stage columns (claimed_amount + remarks).
  UPDATE pre_auth
     SET claimed_amount = NULLIF(data_json->>'claimed_amount','')::numeric,
         remarks        = data_json->>'remarks'
   WHERE stage = 'CLAIM';

  -- 6c. Backfill pre_auth_patient from data_json.patient_insured.
  INSERT INTO pre_auth_patient (
      form_data_id, patient_name, gender, address, age_years, occupation,
      employee_id, date_of_birth, policy_number, contact_number, corporate_name,
      insured_card_id, has_other_insurance, has_family_physician,
      family_physician_name, family_physician_contact, other_insurance_company,
      other_insurance_details, relative_contact_number)
  SELECT fd.id,
         pi->>'patient_name', pi->>'gender', pi->>'address',
         NULLIF(pi->>'age_years','')::int, pi->>'occupation', pi->>'employee_id',
         NULLIF(pi->>'date_of_birth','')::date, pi->>'policy_number',
         pi->>'contact_number', pi->>'corporate_name', pi->>'insured_card_id',
         NULLIF(pi->>'has_other_insurance','')::boolean,
         NULLIF(pi->>'has_family_physician','')::boolean,
         pi->>'family_physician_name', pi->>'family_physician_contact',
         pi->>'other_insurance_company', pi->>'other_insurance_details',
         pi->>'relative_contact_number'
  FROM pre_auth fd
  CROSS JOIN LATERAL (SELECT fd.data_json->'patient_insured' AS pi) x
  WHERE fd.stage = 'PRE_AUTH'
    AND fd.data_json ? 'patient_insured'
  ON CONFLICT (form_data_id) DO NOTHING;

  -- 6d. Backfill pre_auth_treatment from data_json.treating_doctor (+ sub-objects).
  INSERT INTO pre_auth_treatment (
      form_data_id, doctor_name, provisional_diagnosis, icd10_code, surgery_name,
      surgery_icd_code, drug_route, injury_cause, past_history, duration_days,
      other_treatment, critical_findings, treatment_details, illness_description,
      first_consultation_date, tp_investigation, tp_intensive_care,
      tp_non_allopathic, tp_medical_management, tp_surgical_management,
      ad_is_rta, ad_substance_abuse, ad_reported_to_police, ad_test_conducted)
  SELECT fd.id,
         td->>'doctor_name', td->>'provisional_diagnosis', td->>'icd10_code',
         td->>'surgery_name', td->>'surgery_icd_code', td->>'drug_route',
         td->>'injury_cause', td->>'past_history',
         NULLIF(td->>'duration_days','')::int,
         td->>'other_treatment', td->>'critical_findings', td->>'treatment_details',
         td->>'illness_description',
         NULLIF(td->>'first_consultation_date','')::date,
         NULLIF(td#>>'{treatment_plan,investigation}','')::boolean,
         NULLIF(td#>>'{treatment_plan,intensive_care}','')::boolean,
         NULLIF(td#>>'{treatment_plan,non_allopathic}','')::boolean,
         NULLIF(td#>>'{treatment_plan,medical_management}','')::boolean,
         NULLIF(td#>>'{treatment_plan,surgical_management}','')::boolean,
         NULLIF(td#>>'{accident_details,is_rta}','')::boolean,
         NULLIF(td#>>'{accident_details,substance_abuse}','')::boolean,
         NULLIF(td#>>'{accident_details,reported_to_police}','')::boolean,
         td#>>'{accident_details,test_conducted}'
  FROM pre_auth fd
  CROSS JOIN LATERAL (SELECT fd.data_json->'treating_doctor' AS td) x
  WHERE fd.stage = 'PRE_AUTH'
    AND fd.data_json ? 'treating_doctor'
  ON CONFLICT (form_data_id) DO NOTHING;

  -- 6e. Backfill pre_auth_stay from data_json.hospitalization (+ costs/chronic).
  INSERT INTO pre_auth_stay (
      form_data_id, room_type, is_emergency, icu_days, expected_days,
      admission_date, admission_time, room_rent, ot_charges, icu_charges,
      medicines_cost, investigation_cost, professional_fees, package_charges,
      other_expenses, total_cost, cc_diabetes, cc_hypertension, cc_heart_disease,
      cc_asthma_copd, cc_cancer, cc_hiv_std, cc_hyperlipidemia, cc_osteoarthritis,
      cc_alcohol_drug_abuse)
  SELECT fd.id,
         h->>'room_type',
         NULLIF(h->>'is_emergency','')::boolean,
         NULLIF(h->>'icu_days','')::int,
         NULLIF(h->>'expected_days','')::int,
         NULLIF(h->>'admission_date','')::date,
         h->>'admission_time',
         NULLIF(h#>>'{costs,room_rent}','')::numeric,
         NULLIF(h#>>'{costs,ot_charges}','')::numeric,
         NULLIF(h#>>'{costs,icu_charges}','')::numeric,
         NULLIF(h#>>'{costs,medicines_cost}','')::numeric,
         NULLIF(h#>>'{costs,investigation_cost}','')::numeric,
         NULLIF(h#>>'{costs,professional_fees}','')::numeric,
         NULLIF(h#>>'{costs,package_charges}','')::numeric,
         NULLIF(h#>>'{costs,other_expenses}','')::numeric,
         NULLIF(h#>>'{costs,total_cost}','')::numeric,
         NULLIF(h#>>'{chronic_conditions,diabetes}','')::boolean,
         NULLIF(h#>>'{chronic_conditions,hypertension}','')::boolean,
         NULLIF(h#>>'{chronic_conditions,heart_disease}','')::boolean,
         NULLIF(h#>>'{chronic_conditions,asthma_copd}','')::boolean,
         NULLIF(h#>>'{chronic_conditions,cancer}','')::boolean,
         NULLIF(h#>>'{chronic_conditions,hiv_std}','')::boolean,
         NULLIF(h#>>'{chronic_conditions,hyperlipidemia}','')::boolean,
         NULLIF(h#>>'{chronic_conditions,osteoarthritis}','')::boolean,
         NULLIF(h#>>'{chronic_conditions,alcohol_drug_abuse}','')::boolean
  FROM pre_auth fd
  CROSS JOIN LATERAL (SELECT fd.data_json->'hospitalization' AS h) x
  WHERE fd.stage = 'PRE_AUTH'
    AND fd.data_json ? 'hospitalization'
  ON CONFLICT (form_data_id) DO NOTHING;

  -- 6f. Explode bill_breakdown[] into claim_bill_item (claim rows only).
  --     Guarded by NOT EXISTS so reruns don't duplicate lines.
  INSERT INTO claim_bill_item (form_data_id, label, amount, sort_order)
  SELECT fd.id,
         elem->>'label',
         NULLIF(elem->>'amount','')::numeric,
         (ord - 1)
  FROM pre_auth fd
  CROSS JOIN LATERAL jsonb_array_elements(fd.data_json->'bill_breakdown')
    WITH ORDINALITY AS t(elem, ord)
  WHERE fd.stage = 'CLAIM'
    AND jsonb_typeof(fd.data_json->'bill_breakdown') = 'array'
    AND elem->>'label' IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM claim_bill_item cbi WHERE cbi.form_data_id = fd.id
    );

  -- 6g. Drop the legacy data_json column now that everything's migrated.
  ALTER TABLE pre_auth DROP COLUMN data_json;
END $$;

COMMIT;
