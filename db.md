# OASYS Database Reference

This document describes every table in the OASYS backend database: what it is
for, the columns it holds, and how it connects to the other tables. Models live
in `app/models/`.

---

## How the schema fits together (big picture)

OASYS automates the cashless health-insurance workflow between a **hospital**
and a **policy provider / TPA**. The central entity is the **claim case**
(`claim_cases`), which moves through two stages:

- **PRE_AUTH** — the hospital requests pre-authorisation before treatment.
- **CLAIM** — after treatment, the hospital raises the final bill (a `claims`
  row) for settlement.

Around a claim case orbit its **form data**, **emails** (+ attachments),
**supporting documents**, **status history**, **query logs**, and the
provider-side **Part-D authorization letter**.

Identity / configuration tables (`hospitals`, `users`,
`policy_provider_configs`, and their config/mapping siblings) describe *who* is
involved. Template tables (`form_templates`, `email_templates`,
`summary_prompt_templates`, `hospital_prompts`) describe *how* documents and AI
prompts are generated.

```
hospitals ──< users >── policy_provider_configs
   │                              │
   │            ┌─────────────────┘
   ▼            ▼
claim_cases (the hub)
   ├── form_data            (pre-auth form JSON + claim-stage bill breakdown)
   ├── pre_auths            (pre-auth record)
   ├── claims ── settlements (claim stage + final settlement)
   ├── claim_case_emails ── claim_case_email_attachments
   ├── claim_case_documents (categorised supporting files)
   ├── status_history       (audit timeline)
   ├── query_logs           (ADR / "need more info" requests)
   └── part_d_letters       (provider cashless-authorization letter)
```

### Claim-case lifecycle fields (read this first)

`claim_cases` carries three status-like columns that are easy to confuse:

- **`current_stage`** — `PRE_AUTH` or `CLAIM`. Which half of the journey we are in.
- **`status`** — the *workflow* state. One of:
  `DRAFT`, `SUBMITTED`, `ENHANCE_SUBMITTED`, `RECONSIDER`, `ADR_SUBMITTED`,
  `CLAIM_SUBMITTED`, `CLAIM_ADR_SUBMITTED`, `CLAIM_RECONSIDER` (awaiting the
  provider), the outcome states (`APPROVED`, `PARTIALLY_APPROVED`, `DENIED`,
  `ENHANCEMENT_APPROVED`, `ENHANCEMENT_DENIED`, `ADR_NMI`), or `CANCELLED`
  (terminal — hospital withdrew the case).
- **`claim_status`** — the latest *outcome* on the pre-auth (e.g.
  `PARTIALLY_APPROVED`). On pre-auth, only `claim_status` is updated when the
  hospital categorises an insurer reply — `status` can lag, so the authoritative
  "current state" is the newest `status_history` row.

"Awaiting the provider" = `status ∈ {SUBMITTED, ENHANCE_SUBMITTED, RECONSIDER,
ADR_SUBMITTED, CLAIM_SUBMITTED, CLAIM_ADR_SUBMITTED, CLAIM_RECONSIDER}`. This set
drives the provider queue and the "can the hospital cancel?" rule.

---

## Identity & access

### `hospitals`
The hospital tenant. Holds outbound-email credentials so the system can send
mail on the hospital's behalf.

| Column | Use |
|---|---|
| `id` (UUID, PK) | Hospital identifier. |
| `name`, `address`, `rohini_id` | Hospital profile; `rohini_id` is the insurance-network registration id printed on forms. |
| `email` | The hospital's sending mailbox. |
| `app_password` | Encrypted (Fernet) mailbox app-password — never stored plaintext. |
| `created_at`, `updated_at` | Timestamps. |

**Connections:** `users.hospital_id`, `hospital_configs.hospital_id`,
`claim_cases.hospital_id`, `cc_emails.hospital_id`,
`hospital_provider_mappings.hospital_id`, `hospital_prompts.hospital_id`,
`execution_logs.hospital_id`.

### `users`
Login accounts. Role decides what they can do and which tenant they belong to.

| Column | Use |
|---|---|
| `id` (UUID, PK) | User id. |
| `email` (unique) | Login id. |
| `hashed_password` | Bcrypt/argon hash. |
| `role` | `SUPER_ADMIN`, `HOSPITAL_ADMIN`, or `INSURANCE_PROVIDER`. |
| `hospital_id` (FK → hospitals) | Set for hospital admins; scopes their data. |
| `policy_provider_id` (FK → policy_provider_configs) | Set for insurance-provider users; scopes their queue. |
| `access` (text[]) | Feature-flag allow-list. `NULL` = all features, `[]` = none, `[...]` = only those keys. |
| `created_at`, `updated_at` | Timestamps. |

**Connections:** belongs to one `hospitals` *or* one
`policy_provider_configs`. Referenced by `status_history.updated_by`,
`claim_case_emails.validated_by`.

### `policy_provider_configs`
An insurer / TPA. Onboarded providers act inside OASYS; non-onboarded ones are
contacted by email.

| Column | Use |
|---|---|
| `id` (UUID, PK) | Provider id. |
| `provider_id` (unique) | External/business code for the provider. |
| `name` | Display name. |
| `email` | Where pre-auth / claim emails are sent (non-onboarded). |
| `tpa_name`, `tpa_toll_free_phone`, `tpa_toll_free_fax` | TPA header details printed on letters. |
| `config` (JSONB) | Arbitrary provider configuration. |
| `is_onboarded` (bool) | `true` → provider reviews claims in-app via an `INSURANCE_PROVIDER` user; `false` → email workflow. |
| `created_at`, `updated_at` | Timestamps. |

**Connections:** `users.policy_provider_id`,
`claim_cases.policy_provider_id`, `cc_emails.policy_provider_id`,
`hospital_provider_mappings.policy_provider_id`, `form_templates.policy_provider_id`.

### `cc_emails`
Extra CC recipients automatically added to outbound mail, scoped to a hospital
and/or a provider.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Row id. |
| `email` | The CC address. |
| `hospital_id` (FK → hospitals, nullable) | Apply for this hospital. |
| `policy_provider_id` (FK → policy_provider_configs, nullable) | Apply for this provider. |
| `created_at` | Timestamp. |

---

## Hospital configuration & automation

### `hospital_configs`
Per-hospital configuration blob and reusable template variables.

| Column | Use |
|---|---|
| `id` (UUID, PK) | Config id. |
| `hospital_id` (FK → hospitals) | Owner. |
| `config` (JSONB) | Hospital settings. |
| `global_variables` (JSONB) | Key/value fill-ins reused across templates. |
| `created_at`, `updated_at` | Timestamps. |

**Connections:** `hospitals` (back-populates `configs`),
`execution_logs.config_id`.

### `hospital_provider_mappings`
A hospital↔provider agreement (MOU), including parsed room/charge tariffs.
Unique per `(hospital_id, policy_provider_id)`.

| Column | Use |
|---|---|
| `id` (UUID, PK) | Mapping id. |
| `hospital_id` (FK), `policy_provider_id` (FK) | The two parties (unique pair). |
| `room_charges` (JSONB) | Admin-reviewed tariff, e.g. room/ICU/OT per-day rates. |
| `extracted_data` (JSONB) | Raw AI-extracted MOU payload (audit / re-edit). |
| `mou_original_filename`, `mou_stored_filename`, `mou_file_path`, `mou_content_type` | The uploaded MOU document. |
| `is_active` (bool) | Whether the mapping is in force. |
| `created_at`, `updated_at` | Timestamps. |

### `hospital_prompts`
Named, hospital-specific AI prompt snippets.

| Column | Use |
|---|---|
| `id` (UUID, PK) | Prompt id. |
| `hospital_id` (FK → hospitals) | Owner. |
| `name` | Prompt label. |
| `prompt_text` | The prompt body. |
| `created_at`, `updated_at` | Timestamps. |

### `execution_logs`
Audit of automated runs (e.g. config-driven jobs) per hospital.

| Column | Use |
|---|---|
| `id` (UUID, PK) | Log id. |
| `hospital_id` (FK → hospitals) | Which hospital. |
| `config_id` (FK → hospital_configs) | Which config produced the run. |
| `status` | `success` / `failure`. |
| `request_data`, `response_data` (JSONB) | Payloads in/out. |
| `error` | Failure message, if any. |
| `created_at` | Timestamp. |

---

## Claim-case core

### `claim_cases`  ← the hub
One per patient pre-auth / claim journey. Almost everything FKs back to this.

| Column | Use |
|---|---|
| `id` (UUID, PK) | Claim-case id (used throughout the app + in email subjects). |
| `uhid` | Hospital's unique patient id. |
| `hospital_id` (FK → hospitals, nullable) | Owning hospital. |
| `policy_provider_id` (FK → policy_provider_configs) | The insurer/TPA. |
| `claim_number` | PA / claim reference number. |
| `current_stage` | `PRE_AUTH` or `CLAIM` (default `PRE_AUTH`). |
| `status` | Workflow state (see lifecycle section). Default `DRAFT`. |
| `claim_status` | Latest pre-auth outcome. |
| `approved_amount` | Cumulative approved amount (pre-auth side). |
| `thread_id` (unique) | Short id embedded in email subjects to thread replies back to this case. |
| `created_at`, `updated_at` | Timestamps. |

**Connections (children):** `pre_auths`, `claims`, `status_history`,
`form_data`, `query_logs`, `claim_case_emails`, `claim_case_documents`,
`claim_case_email_attachments`, `part_d_letters`. **Parents:** `hospitals`,
`policy_provider_configs`.

### `form_data`
The structured form payload for a case. Stores the **pre-auth form JSON** and,
with `data_json.stage = "CLAIM"`, the **claim-stage bill breakdown**. Also used
for **claim drafts** (`stage=CLAIM, status=DRAFT`).

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Row id. |
| `claim_case_id` (FK → claim_cases, nullable) | Owning case. |
| `data_json` (JSONB) | The form content. `stage` key separates pre-auth vs claim rows. |
| `status` | `DRAFT` / `SUBMITTED` (free-form text). |
| `created_at`, `updated_at` | Timestamps. |

**Connections:** `claim_cases` (back-populates `form_data`); referenced by
`pre_auths.form_data_id`.

### `pre_auths`
A pre-authorisation record tied 1:1 to a case and a form-data snapshot.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Row id. |
| `claim_case_id` (FK → claim_cases, unique) | Owning case (one per case). |
| `form_data_id` (FK → form_data) | The submitted form snapshot. |
| `status` | Pre-auth status (default `PENDING`). |
| `request_date`, `response_date` | When sent / answered. |
| `approved_amount` | Amount approved on the pre-auth. |
| `remarks` | Free text. |
| `created_at` | Timestamp. |

### `claims`
The final bill raised in the CLAIM stage. One per case.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Claim id. |
| `claim_case_id` (FK → claim_cases, unique) | Owning case (one claim per case). |
| `claimed_amount` (NOT NULL) | Total bill submitted (used as "Claim Raised" amount). |
| `approved_amount` | Insurer's claim-stage approval (used as "Claim Approved" amount). |
| `status` | Claim status (default `SUBMITTED`). |
| `submitted_at`, `processed_at`, `created_at` | Timestamps. |

**Connections:** `claim_cases` (1:1), `settlements` (1:1).

### `settlements`
The money actually settled against a claim. One per claim.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Settlement id. |
| `claim_id` (FK → claims, unique) | The claim being settled. |
| `settled_amount` (NOT NULL) | Amount paid. |
| `status` | Default `INITIATED`. |
| `settlement_date` | When settled. |
| `created_at` | Timestamp. |

### `status_history`
Append-only audit timeline of every status change on a case. The newest row is
the authoritative "current state" (since `claim_cases.status` can lag on
pre-auth). Powers the Status Timeline UI and the per-step TAT figures.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Row id. |
| `claim_case_id` (FK → claim_cases) | Owning case. |
| `stage` | `PRE_AUTH` or `CLAIM` at the time of the change. |
| `status` | The status this row records (e.g. `SUBMITTED`, `PARTIALLY_APPROVED`, `CANCELLED`). |
| `remarks` | Note / reason (e.g. cancellation reason). |
| `approved_amount` | Amount approved in *this* round (not cumulative). |
| `email_id` (FK → claim_case_emails, nullable) | The email that produced the change. |
| `changed_by` | Source label (`MANUAL_EDIT`, `HOSPITAL_ADMIN`, …). |
| `updated_by` (FK → users, nullable) | Acting user. |
| `created_at` | When the change happened. |

### `query_logs`
Tracks insurer "Additional Documents Required / Need More Info" (ADR_NMI)
requests on a case.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Row id. |
| `claim_case_id` (FK → claim_cases) | Owning case. |
| `query_type` | e.g. `ADR_NMI`. |
| `query_details` | The insurer's question. |
| `documents_requested` | Free-text list. |
| `documents_list` (JSONB) | AI-extracted structured list of requested document names. |
| `status` | `OPEN` / `RESOLVED`. |
| `resolved_at`, `created_at` | Timestamps. |

---

## Email & documents

### `claim_case_emails`
Every inbound (`RECEIVED`) and outbound (`SENT`) email on a case, plus the AI's
extracted suggestions used to categorise insurer replies.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Email id. |
| `claim_case_id` (FK → claim_cases) | Owning case. |
| `direction` | `SENT` / `RECEIVED`. |
| `from_email`, `to_email`, `subject`, `body` | Email content. |
| `message_id` (unique) | RFC message id; used for inbound dedup + threading. |
| `email_type` | Workflow type: `SUBMITTED`, `ENHANCE_SUBMITTED`, `RECONSIDER`, `ADR_SUBMITTED`, `APPROVAL`, `PARTIAL_APPROVAL`, `DENIAL`, `ENHANCEMENT_*`, `ADR_NMI`, `CLAIM_*`, `CANCELLED`. |
| `thread_id` | Mirrors the case thread id for matching. |
| `email_date` | Provider/inbox timestamp. |
| `is_read` | Hospital-admin read flag (drives the uncategorised badge). |
| `provider_read` | In-app insurance-provider read flag. |
| `ai_suggested_status`, `ai_suggested_amount`, `ai_suggested_claim_number` | AI extraction of the reply. |
| `ai_summary`, `ai_query_details`, `ai_documents_requested`, `ai_documents_list` (JSONB) | AI-parsed reply detail. |
| `ai_approved_breakdown` (JSONB), `ai_denial_reason` | Claim-stage extras (per-line approvals / denial reason). |
| `form_values` (JSONB) | Structured payload the hospital submitted (e.g. enhancement `additional_amount`, `revised_total`, `reason_*`). |
| `validation_status`, `validated_at`, `validated_by` (FK → users) | Human validation of the AI suggestion. |
| `created_at` | Timestamp. |

**Connections:** `claim_cases`; has many `claim_case_email_attachments`
(cascade delete). Referenced by `status_history.email_id`,
`claim_case_documents.sent_email_id`, `part_d_letters.claim_case_email_id`.

### `claim_case_email_attachments`
Files attached to a specific email.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Attachment id. |
| `email_id` (FK → claim_case_emails) | Owning email. |
| `claim_case_id` (FK → claim_cases) | Denormalised case id for fast filtering. |
| `original_filename`, `stored_filename`, `file_path` | The file on disk. |
| `content_type`, `file_size` | File metadata. |
| `document_type` | Mirrors `claim_case_documents.document_type` when sourced from a categorised doc; else `NULL`. |
| `created_at` | Timestamp. |

### `claim_case_documents`
Supporting documents uploaded for a case (and later attached to outbound mail).

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Document id. |
| `claim_case_id` (FK → claim_cases) | Owning case. |
| `original_filename`, `stored_filename`, `file_path` | The file on disk. |
| `content_type`, `file_size` | File metadata. |
| `sent_email_id` (FK → claim_case_emails, nullable) | The outbound email it was attached to. `NULL` = uploaded but not yet sent (e.g. held under a claim draft). |
| `document_type` | Category (e.g. `CONSOLIDATED_BILLS`, `DISCHARGE_SUMMARY`, `AUTHORIZATION_LETTERS`). |
| `created_at` | Timestamp. |

### `part_d_letters`
The editable field values for a provider's Part-D (Cashless Authorization
Letter), one per approval-round email. Lets the provider's modal prefill instead
of retyping the bill breakdown / authorisation summary.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Row id. |
| `claim_case_id` (FK → claim_cases) | Owning case. |
| `claim_case_email_id` (FK → claim_case_emails, nullable) | The approval email this letter belongs to. `NULL` = a pre-approval draft (at most one per case). |
| `attachment_id` (FK → claim_case_email_attachments, nullable) | The rendered PDF once printed/attached. |
| `approved_amount`, `claim_number` | Header values frozen on the letter. |
| `room_rent_per_day`, `icu_rent_per_day`, `nursing_charges_per_day`, `consultant_visit_charges_per_day`, `surgeon_anesthetist_fee`, `others` | Bill-breakdown free-text fields (printed verbatim). |
| `total_bill_amount`, `deductions_detail`, `discount`, `co_pay`, `deductibles`, `total_authorised_amount`, `amount_to_be_paid_by_insured` | Authorisation-summary free-text fields. |
| `remarks` | Free text. |
| `created_at`, `updated_at` | Timestamps. |

**Uniqueness:** partial unique indexes ensure at most one Part-D per approval
email, and at most one draft (email id `NULL`) per case.

---

## Templates & prompts

### `form_templates`
HTML templates rendered into forms/letters, per provider and form type.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Template id. |
| `name`, `version` | Identity (unique with `form_type`). |
| `form_type` | `PRE_AUTH`, `FORM_C`, `PART_D`, … (default `PRE_AUTH`). |
| `html_content` | The template markup. |
| `policy_provider_id` (FK → policy_provider_configs) | Owning provider. |
| `is_active` | Whether it is selectable. |
| `created_at` | Timestamp. |

Unique on `(name, version, form_type)`.

### `email_templates`
Reusable named email bodies/subjects (global, not provider-scoped).

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Template id. |
| `name`, `subject`, `body` | The template. |
| `is_active` | Whether it is selectable. |
| `created_at` | Timestamp. |

### `summary_prompt_templates`
Keyed AI prompt templates used to generate summaries.

| Column | Use |
|---|---|
| `id` (UUID, PK) | Row id. |
| `key` (unique) | Lookup key. |
| `prompt_text` | The prompt. |
| `created_at`, `updated_at` | Timestamps. |

---

## Platform / misc

### `features`
Feature-flag catalogue. `users.access` references these keys to gate tabs.

| Column | Use |
|---|---|
| `id` (UUID, PK) | Row id. |
| `key` (unique) | Feature key (matched against `users.access`). |
| `label` | Human label. |
| `is_active` | Whether the feature is live. |
| `created_at`, `updated_at` | Timestamps. |

### `patients`
Standalone minimal patient record (name/age/gender). Patient identity in the
claim workflow is normally carried inside `form_data.data_json`; this table is a
lightweight lookup.

| Column | Use |
|---|---|
| `id` (BigInt, PK) | Patient id. |
| `name`, `age`, `gender` | Basic demographics. |
| `created_at` | Timestamp. |

---

## Quick relationship index

| Table | References (FK →) | Referenced by |
|---|---|---|
| `hospitals` | — | users, hospital_configs, claim_cases, cc_emails, hospital_provider_mappings, hospital_prompts, execution_logs |
| `users` | hospitals, policy_provider_configs | status_history.updated_by, claim_case_emails.validated_by |
| `policy_provider_configs` | — | users, claim_cases, cc_emails, hospital_provider_mappings, form_templates |
| `hospital_configs` | hospitals | execution_logs |
| `hospital_provider_mappings` | hospitals, policy_provider_configs | — |
| `hospital_prompts` | hospitals | — |
| `execution_logs` | hospitals, hospital_configs | — |
| `claim_cases` | hospitals, policy_provider_configs | pre_auths, claims, form_data, status_history, query_logs, claim_case_emails, claim_case_documents, claim_case_email_attachments, part_d_letters |
| `form_data` | claim_cases | pre_auths.form_data_id |
| `pre_auths` | claim_cases, form_data | — |
| `claims` | claim_cases | settlements |
| `settlements` | claims | — |
| `status_history` | claim_cases, claim_case_emails, users | — |
| `query_logs` | claim_cases | — |
| `claim_case_emails` | claim_cases, users (validated_by) | claim_case_email_attachments, status_history, claim_case_documents.sent_email_id, part_d_letters |
| `claim_case_email_attachments` | claim_case_emails, claim_cases | part_d_letters.attachment_id |
| `claim_case_documents` | claim_cases, claim_case_emails (sent_email_id) | — |
| `part_d_letters` | claim_cases, claim_case_emails, claim_case_email_attachments | — |
| `form_templates` | policy_provider_configs | — |
| `email_templates` | — | — |
| `summary_prompt_templates` | — | — |
| `features` | — | (logical) users.access |
| `patients` | — | — |
