-- Deploy the final-state schema on a target DB.
--
-- Designed to be SAFE to run on:
--   • a freshly-WIPED production DB that's still on the OLD schema
--     (i.e. you ran `TRUNCATE claim_cases CASCADE; DROP TABLE IF EXISTS pre_auths;`
--      first, OR the DB was started from a backup taken before any of this work
--      and you don't need to preserve case data), and
--   • a DB that already has the NEW schema (rerunning is a no-op).
--
-- It does NOT migrate data out of `data_json` — for that one-time migration
-- with the old data in place, see the historical scripts in this folder.
--
-- Usage:
--   PGPASSWORD=... psql -h <host> -U admin -d <target> -v ON_ERROR_STOP=1 \
--     -f scripts/deploy_schema.sql

BEGIN;

-- 1. Drop the dead pre_auths table (legacy, never populated)
DROP TABLE IF EXISTS pre_auths;

-- 2. Rename hub + form tables (idempotent — skipped if already renamed)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema = 'public' AND table_name = 'claim_cases') THEN
    ALTER TABLE claim_cases RENAME TO hospitalization;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema = 'public' AND table_name = 'form_data') THEN
    ALTER TABLE form_data RENAME TO pre_auth;
  END IF;
END $$;
-- Child FKs auto-follow the rename (Postgres references parents by OID, not name).

-- 3. New columns on pre_auth (stage discriminator + claim-stage fields)
ALTER TABLE pre_auth ADD COLUMN IF NOT EXISTS stage VARCHAR NOT NULL DEFAULT 'PRE_AUTH';
ALTER TABLE pre_auth ADD COLUMN IF NOT EXISTS claimed_amount NUMERIC(12,2);
ALTER TABLE pre_auth ADD COLUMN IF NOT EXISTS remarks TEXT;

-- 4. Drop the legacy data_json blob (no longer used; pre-auth + claim-stage
--    data now live in typed tables/columns)
ALTER TABLE pre_auth DROP COLUMN IF EXISTS data_json;

-- 5. Structured pre-auth section tables (1:1 with the pre_auth row)
CREATE TABLE IF NOT EXISTS pre_auth_patient (
    id                       BIGSERIAL PRIMARY KEY,
    form_data_id             BIGINT NOT NULL UNIQUE
                              REFERENCES pre_auth(id) ON DELETE CASCADE,
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
CREATE INDEX IF NOT EXISTS ix_pre_auth_patient_form_data_id
  ON pre_auth_patient(form_data_id);

CREATE TABLE IF NOT EXISTS pre_auth_treatment (
    id                      BIGSERIAL PRIMARY KEY,
    form_data_id            BIGINT NOT NULL UNIQUE
                             REFERENCES pre_auth(id) ON DELETE CASCADE,
    doctor_name             TEXT,
    provisional_diagnosis   TEXT,
    icd10_code              TEXT,
    surgery_icd_code        TEXT,   -- ICD-10-PCS procedure code
    drug_route              JSONB,  -- array of DRUG_ROUTES codes, e.g. ["IV","PO"]
    injury_cause            TEXT,
    past_history            TEXT,
    duration_days           INTEGER,
    critical_findings       TEXT,
    treatment_details       TEXT,
    illness_description     TEXT,
    first_consultation_date DATE,
    -- Ordered array of {treatment_details, drug_route[], surgery_icd_code,
    -- injury_cause}. The scalar columns above mirror entry #1 for the print/email.
    treatments              JSONB,
    -- Ordered array of {investigation_category, investigation_name,
    -- investigation_description}; revealed by tp_investigation.
    investigations          JSONB,
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
CREATE INDEX IF NOT EXISTS ix_pre_auth_treatment_form_data_id
  ON pre_auth_treatment(form_data_id);

CREATE TABLE IF NOT EXISTS pre_auth_stay (
    id                    BIGSERIAL PRIMARY KEY,
    form_data_id          BIGINT NOT NULL UNIQUE
                           REFERENCES pre_auth(id) ON DELETE CASCADE,
    room_type             TEXT,
    is_emergency          BOOLEAN,
    icu_days              INTEGER,
    expected_days         INTEGER,
    admission_date        DATE,
    admission_time        TEXT,
    -- costs.*
    room_rent             NUMERIC(12,2),
    ot_charges            NUMERIC(12,2),
    icu_charges           NUMERIC(12,2),
    medicines_cost        NUMERIC(12,2),
    investigation_cost    NUMERIC(12,2),
    professional_fees     NUMERIC(12,2),
    package_charges       NUMERIC(12,2),
    other_expenses        NUMERIC(12,2),
    total_cost            NUMERIC(12,2),
    -- chronic_conditions.*
    cc_diabetes           BOOLEAN,
    cc_hypertension       BOOLEAN,
    cc_heart_disease      BOOLEAN,
    cc_asthma_copd        BOOLEAN,
    cc_cancer             BOOLEAN,
    cc_hiv_std            BOOLEAN,
    cc_hyperlipidemia     BOOLEAN,
    cc_osteoarthritis     BOOLEAN,
    cc_alcohol_drug_abuse BOOLEAN,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pre_auth_stay_form_data_id
  ON pre_auth_stay(form_data_id);

-- 6. Claim-stage bill-breakdown line items
CREATE TABLE IF NOT EXISTS claim_bill_item (
    id           BIGSERIAL PRIMARY KEY,
    form_data_id BIGINT NOT NULL REFERENCES pre_auth(id) ON DELETE CASCADE,
    label        TEXT NOT NULL,
    amount       NUMERIC(12,2) NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_claim_bill_item_form_data_id
  ON claim_bill_item(form_data_id);

-- 7. Invoice (one per case; raised after a claim is approved). Status is
--    auto-derived from payments (PAID / PARTIALLY_PAID / UNPAID).
CREATE TABLE IF NOT EXISTS invoice (
    id                  BIGSERIAL PRIMARY KEY,
    claim_case_id       UUID NOT NULL UNIQUE
                          REFERENCES hospitalization(id) ON DELETE CASCADE,
    insurer_invoice_id  VARCHAR NOT NULL,
    insurer_amount      NUMERIC(12,2) NOT NULL,
    status              VARCHAR NOT NULL DEFAULT 'UNPAID',
                          -- PAID | PARTIALLY_PAID | UNPAID
    created_by_user_id  UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_invoice_status ON invoice(status);

-- 8. Invoice payment line items (N per invoice; each row has its own
--    reference_id, UTR / settlement id / etc.).
CREATE TABLE IF NOT EXISTS invoice_payment (
    id            BIGSERIAL PRIMARY KEY,
    invoice_id    BIGINT NOT NULL REFERENCES invoice(id) ON DELETE CASCADE,
    payment_date  DATE NOT NULL,
    amount        NUMERIC(12,2) NOT NULL,
    reference_id  VARCHAR,
    note          TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_invoice_payment_invoice_id
  ON invoice_payment(invoice_id);

COMMIT;
