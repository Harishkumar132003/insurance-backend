-- ⚠️  HISTORICAL — DO NOT RUN ON PRODUCTION.
-- One-time dev migration used to backfill the pre-auth typed tables
-- (pre_auth_patient / pre_auth_treatment / pre_auth_stay) from the OLD
-- `form_data.data_json` column on the `oasysbackup` sandbox. The `data_json`
-- column has since been dropped, so this script will FAIL on a current DB.
-- Kept here only as a reference for how the column→JSON-key mapping was
-- derived. For greenfield/wipe deploys use `scripts/deploy_schema.sql`.
--
-- Pre-auth form normalization: split form_data.data_json into typed tables.
-- Tables are 1:1 with the pre-auth form_data row (anchor = form_data_id).
-- Idempotent: safe to re-run (DROP + CREATE + reload).
--
-- Run against the sandbox first:
--   PGPASSWORD=... psql -h localhost -U admin -d oasysbackup -f scripts/pre_auth_normalization.sql

BEGIN;

DROP TABLE IF EXISTS pre_auth_patient;
DROP TABLE IF EXISTS pre_auth_treatment;
DROP TABLE IF EXISTS pre_auth_stay;

-- ── patient_insured ────────────────────────────────────────────────
CREATE TABLE pre_auth_patient (
    id                       BIGSERIAL PRIMARY KEY,
    form_data_id             BIGINT NOT NULL UNIQUE REFERENCES form_data(id) ON DELETE CASCADE,
    patient_name             TEXT,
    gender                   TEXT,
    address                  TEXT,
    age_years                INTEGER,
    occupation               TEXT,
    employee_id              TEXT,
    date_of_birth            DATE,
    policy_number            TEXT,
    contact_number           TEXT,
    corporate_name           TEXT,
    insured_card_id          TEXT,
    has_other_insurance      BOOLEAN,
    has_family_physician     BOOLEAN,
    family_physician_name    TEXT,
    family_physician_contact TEXT,
    other_insurance_company  TEXT,
    other_insurance_details  TEXT,
    relative_contact_number  TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── treating_doctor (+ treatment_plan, accident_details) ───────────
CREATE TABLE pre_auth_treatment (
    id                      BIGSERIAL PRIMARY KEY,
    form_data_id            BIGINT NOT NULL UNIQUE REFERENCES form_data(id) ON DELETE CASCADE,
    doctor_name             TEXT,
    provisional_diagnosis   TEXT,
    icd10_code              TEXT,
    surgery_name            TEXT,
    surgery_icd_code        TEXT,
    drug_route              TEXT,
    injury_cause            TEXT,
    past_history            TEXT,
    duration_days           INTEGER,
    other_treatment         TEXT,
    critical_findings       TEXT,
    treatment_details       TEXT,
    illness_description     TEXT,
    first_consultation_date DATE,
    -- treatment_plan.*
    tp_investigation        BOOLEAN,
    tp_intensive_care       BOOLEAN,
    tp_non_allopathic       BOOLEAN,
    tp_medical_management   BOOLEAN,
    tp_surgical_management  BOOLEAN,
    -- accident_details.*
    ad_is_rta               BOOLEAN,
    ad_substance_abuse      BOOLEAN,
    ad_reported_to_police   BOOLEAN,
    ad_test_conducted       TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── hospitalization (+ costs, chronic_conditions) ──────────────────
CREATE TABLE pre_auth_stay (
    id                  BIGSERIAL PRIMARY KEY,
    form_data_id        BIGINT NOT NULL UNIQUE REFERENCES form_data(id) ON DELETE CASCADE,
    room_type           TEXT,
    is_emergency        BOOLEAN,
    icu_days            INTEGER,
    expected_days       INTEGER,
    admission_date      DATE,
    admission_time      TEXT,
    -- costs.*
    room_rent           NUMERIC(12,2),
    ot_charges          NUMERIC(12,2),
    icu_charges         NUMERIC(12,2),
    medicines_cost      NUMERIC(12,2),
    investigation_cost  NUMERIC(12,2),
    professional_fees   NUMERIC(12,2),
    package_charges     NUMERIC(12,2),
    other_expenses      NUMERIC(12,2),
    total_cost          NUMERIC(12,2),
    -- chronic_conditions.*
    cc_diabetes         BOOLEAN,
    cc_hypertension     BOOLEAN,
    cc_heart_disease    BOOLEAN,
    cc_asthma_copd      BOOLEAN,
    cc_cancer           BOOLEAN,
    cc_hiv_std          BOOLEAN,
    cc_hyperlipidemia   BOOLEAN,
    cc_osteoarthritis   BOOLEAN,
    cc_alcohol_drug_abuse BOOLEAN,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Backfill from existing data_json (pre-auth rows only) ──────────
-- Helper casts: NULLIF(...,'') guards empty strings before ::date / ::numeric.

INSERT INTO pre_auth_patient (
    form_data_id, patient_name, gender, address, age_years, occupation,
    employee_id, date_of_birth, policy_number, contact_number, corporate_name,
    insured_card_id, has_other_insurance, has_family_physician,
    family_physician_name, family_physician_contact, other_insurance_company,
    other_insurance_details, relative_contact_number
)
SELECT
    fd.id,
    pi->>'patient_name',
    pi->>'gender',
    pi->>'address',
    NULLIF(pi->>'age_years','')::int,
    pi->>'occupation',
    pi->>'employee_id',
    NULLIF(pi->>'date_of_birth','')::date,
    pi->>'policy_number',
    pi->>'contact_number',
    pi->>'corporate_name',
    pi->>'insured_card_id',
    NULLIF(pi->>'has_other_insurance','')::boolean,
    NULLIF(pi->>'has_family_physician','')::boolean,
    pi->>'family_physician_name',
    pi->>'family_physician_contact',
    pi->>'other_insurance_company',
    pi->>'other_insurance_details',
    pi->>'relative_contact_number'
FROM form_data fd
CROSS JOIN LATERAL (SELECT fd.data_json->'patient_insured' AS pi) x
WHERE (fd.data_json->>'stage') IS DISTINCT FROM 'CLAIM'
  AND fd.data_json ? 'patient_insured';

INSERT INTO pre_auth_treatment (
    form_data_id, doctor_name, provisional_diagnosis, icd10_code, surgery_name,
    surgery_icd_code, drug_route, injury_cause, past_history, duration_days,
    other_treatment, critical_findings, treatment_details, illness_description,
    first_consultation_date, tp_investigation, tp_intensive_care,
    tp_non_allopathic, tp_medical_management, tp_surgical_management,
    ad_is_rta, ad_substance_abuse, ad_reported_to_police, ad_test_conducted
)
SELECT
    fd.id,
    td->>'doctor_name',
    td->>'provisional_diagnosis',
    td->>'icd10_code',
    td->>'surgery_name',
    td->>'surgery_icd_code',
    td->>'drug_route',
    td->>'injury_cause',
    td->>'past_history',
    NULLIF(td->>'duration_days','')::int,
    td->>'other_treatment',
    td->>'critical_findings',
    td->>'treatment_details',
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
FROM form_data fd
CROSS JOIN LATERAL (SELECT fd.data_json->'treating_doctor' AS td) x
WHERE (fd.data_json->>'stage') IS DISTINCT FROM 'CLAIM'
  AND fd.data_json ? 'treating_doctor';

INSERT INTO pre_auth_stay (
    form_data_id, room_type, is_emergency, icu_days, expected_days,
    admission_date, admission_time, room_rent, ot_charges, icu_charges,
    medicines_cost, investigation_cost, professional_fees, package_charges,
    other_expenses, total_cost, cc_diabetes, cc_hypertension, cc_heart_disease,
    cc_asthma_copd, cc_cancer, cc_hiv_std, cc_hyperlipidemia, cc_osteoarthritis,
    cc_alcohol_drug_abuse
)
SELECT
    fd.id,
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
FROM form_data fd
CROSS JOIN LATERAL (SELECT fd.data_json->'hospitalization' AS h) x
WHERE (fd.data_json->>'stage') IS DISTINCT FROM 'CLAIM'
  AND fd.data_json ? 'hospitalization';

COMMIT;
