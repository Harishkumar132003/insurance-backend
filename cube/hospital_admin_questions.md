# Hospital-admin questions the AI can answer

Reference / coverage list of natural-language questions a hospital admin might ask
the `/api/v1/ai/intent` endpoint, grouped by theme and mapped to the cube member
that answers them. Everything here is served by the `pre_auth`, `claims`,
`hospitals` and `hospitalization` cubes.

Notes:
- Statuses on `claims` are `CLAIM_`-prefixed internally, but ask in plain words
  ("approved", "denied") — the model maps them.
- Time works with relative buckets ("this month", "last 30 days") or explicit
  ranges ("in June", "between June 20 and 30").
- ⚠️ Items marked **[needs hub joins]** aren't wired yet (see bottom).

---

## 1. Pre-auth — volume & status
- How many pre-auths do we have?  → `pre_auth.count`
- How many pre-auths are pending / awaiting the insurer?  → segment `pre_auth.pending`
- How many pre-auths were submitted (initial)?  → segment `pre_auth.submitted`
- How many enhancement requests are submitted?  → segment `pre_auth.enhancement_submitted`
- How many ADR replies are we waiting on?  → segment `pre_auth.adr_submitted`
- How many pre-auths are in reconsideration?  → segment `pre_auth.reconsideration`
- How many pre-auths **need action from our side**?  → `pre_auth.action_needed_count`
- How many open ADR/queries did the insurer raise?  → segment `pre_auth.adr_query`
- How many pre-auths were approved?  → segment `pre_auth.approved_any`
- How many were fully approved vs partially approved?  → `pre_auth.fully_approved` / `pre_auth.partially_approved`
- How many enhancement requests were approved?  → segment `pre_auth.enhancement_approved`
- How many pre-auths were denied?  → segment `pre_auth.denied`
- How many pre-auths were cancelled?  → segment `pre_auth.cancelled`
- How many pre-auths went through an ADR / enhancement?  → `pre_auth.has_adr` / `pre_auth.has_enhancement`

## 2. Pre-auth — amounts
- Total requested (raised) pre-auth amount  → `pre_auth.total_raised_amount`
- Total approved pre-auth amount  → `pre_auth.total_approved_amount`
- Average requested / approved pre-auth amount  → `pre_auth.avg_raised_amount` / `avg_approved_amount`
- How much money is stuck as unapproved shortfall?  → `pre_auth.total_shortfall_amount`
- How many big-ticket pre-auths (≥ ₹1,00,000)?  → segment `pre_auth.high_value`
- How many pre-auths have an approved amount yet / not yet?  → `approved_any` / `awaiting_approval_amount`

## 3. Claims — volume & status
- How many claims do we have?  → `claims.count`
- How many claims are pending / awaiting decision?  → segment `claims.pending` (or `claims.pending_count`)
- How many claims are submitted?  → segment `claims.submitted`
- How many claims need action from our side?  → segment `claims.action_needed`
- How many claims have an open insurer query (ADR)?  → segment `claims.adr_query`
- How many claims are in reconsideration?  → segment `claims.reconsideration`
- How many claims were approved?  → segment `claims.approved_any`
- How many fully vs partially approved claims?  → `claims.fully_approved` / `claims.partially_approved`
- How many claims were denied?  → segment `claims.denied` (or `claims.denied_count`)
- How many claims have been processed / decided?  → `claims.processed` / `claims.processed_count`
- How many claims are still open (undecided)?  → segment `claims.open`

## 4. Claims — amounts
- Total claimed amount  → `claims.total_claimed_amount`
- Total approved claim amount  → `claims.total_approved_amount`
- Total approved claim amount by hospital  → `claims.total_approved_amount` grouped by `hospitals.name`
- Average claimed / approved amount per claim  → `claims.avg_claimed_amount` / `avg_approved_amount`
- Total disallowed amount (claimed − approved)  → `claims.total_disallowed_amount`
- Top 5 hospitals by total claimed amount  → `claims.total_claimed_amount` by `hospitals.name`, top 5
- How many high-value claims (≥ ₹1,00,000)?  → segment `claims.high_value`

## 5. Conversion (pre-auth → claim)
- How many pre-auths converted into claims?  → `claims.conversion_count`
- How many converted this month / in June / last 30 days?  → `claims.conversion_count` + time
- Conversion by hospital  → `claims.conversion_count` grouped by `hospitals.name`

## 5b. Cases (hospitalization) — the case hub
- How many cases do we have?  → `hospitalization.count`
- How many cases are in the pre-auth stage vs claim stage?  → `pre_auth_stage_count` / `claim_stage_count` (or segments `pre_auth_stage` / `claim_stage`)
- How many cases reached the claim stage?  → segment `hospitalization.claim_stage`
- How many cases are cancelled / active?  → `cancelled_count` / `active_count`
- How many cases have an approved pre-auth / a denied pre-auth?  → `preauth_approved` / `preauth_denied`
- How many cases have an approved claim?  → segment `hospitalization.claim_approved`
- How many cases are awaiting a claim decision?  → segment `hospitalization.claim_pending`
- How many cases have a claim number assigned?  → segment `hospitalization.has_claim_number`
- Cases by stage / by status / by provider  → group by `current_stage` / `case_status` / `policy_provider_id`
- Total / average approved amount across cases  → `total_approved_amount` / `avg_approved_amount`
- Cases created this month / last 30 days / this year  → time segments

## 5c. Patients (patient_personal_detail) — demographics & policy
- How many patients do we have?  → `patient_personal_detail.count`
- How many male / female patients?  → segments `male` / `female`
- Patients by gender  → group by `gender`
- Average / youngest / oldest patient age  → `avg_age` / `min_age` / `max_age`
- How many pediatric / adult / senior-citizen patients?  → segments `pediatric` / `adult` / `senior`
- How many patients have other insurance?  → `with_other_insurance_count` (or segment `with_other_insurance`)
- How many patients have a family physician?  → `with_family_physician_count`
- How many corporate patients (employer policy)?  → `corporate_count` (or segment `corporate_patient`)
- Patients by occupation / by corporate  → group by `occupation` / `corporate_name`
- Look up a patient by name / policy number / UHID  → filter on `patient_name` / `policy_number` / `uhid`

## 5d. Patient / UHID lookups (cross-cube via the hospitalization hub)
`patient_name` lives only on `patient_personal_detail`; the case/claim info lives on
`hospitalization` / `claims`. The hospitalization **hub joins** let these combine —
filter by patient name/uhid on one cube, return fields from another.
- Show details for patient <name>  → filter `patient_name` **contains** <name>
- Case status / stage of patient <name>  → filter patient_name → `hospitalization.case_status` / `current_stage`
- Show claims / claim number for patient <name>  → filter patient_name → `claims.claim_number` / `status`
- Approved amount for patient <name>  → filter patient_name → `claims.total_approved_amount`
- How many cases / claims does patient <name> have?  → count with patient_name filter
- What stage / status is UHID <id> in?  → filter `uhid` **equals** <id> → status/stage
- Patient name for UHID <id>  → filter uhid → `patient_name`
- Look up by policy number / claim number  → filter `policy_number` / `claim_number` **equals**

Tips: names use **contains** (partial/forgiving); uhid / claim_number / policy_number
use **equals**. A UHID can map to more than one case in test data — add "the latest"
or expect multiple rows.

## 6. Time-based & trends
- Pre-auths / claims created this month, last 7/30/90 days, this year
- Pre-auths created between June 20 and June 30  → explicit date range
- Monthly trend of pre-auth submissions this year  → `pre_auth.count` by `created_at` (month granularity)
- Monthly trend of claims this year  → `claims.count` by `submitted_at` (month granularity)
- Approved amount this quarter / last quarter

## 7. Grouping / breakdowns
- Pre-auths by status  → `pre_auth.count` grouped by `pre_auth.preauth_status`
- Claims by status  → `claims.count` grouped by `claims.status`
- Approved amount per hospital  → grouped by `hospitals.name`
- Claims / pre-auths per provider  → grouped by provider (via hospitalization.policy_provider_id)

## 8. Records / lookups (lists)
- List denied claims with their claim numbers  → `claims.claim_number` + segment `claims.denied`
- List pending pre-auths
- Show claims above ₹1,00,000  → dimensions + segment `high_value`
- Show a specific case by claim number / UHID  → filter on `claim_number` / `uhid`

## 9. Tenant / hospital
- How many hospitals (tenants) do we have?  → `hospitals.count`
- Which hospital has the most claims / highest claimed amount?  → ranking by `hospitals.name`

---

## Phrasing tips & known limitations
- **Breakdowns** ("by status", "by hospital", "per provider") return one row per
  value — verified working for `pre_auth.preauth_status`, `claims.status`,
  `hospitals.name`.
- **"shortfall" / "disallowed amount"** is ambiguous: the `settlement_item` table
  also has a `disallowance` column, so a bare "disallowed amount" may route there.
  For the pre-auth gap say **"unapproved pre-auth shortfall"** (→
  `pre_auth.total_shortfall_amount`); for the claim gap say **"claim disallowed
  amount"** (→ `claims.total_disallowed_amount`).
- **Status words** work best either as a single named slice ("how many pending")
  or as a breakdown ("by status"); the underlying claim values are `CLAIM_`-prefixed
  but you never need to type the prefix.
- The `aiagent` DB is a **point-in-time snapshot** — "this month" (July) is empty
  until it's refreshed; use June / last-30-days for populated results.

## ⚠️ Questions that need the hospitalization-hub joins (not wired yet)
These require comparing pre_auth and claims across the case, so they need joins
from `hospitalization` → `pre_auth` and → `claims` plus new measures:
- **Conversion rate** — % of pre-auths that became claims (claims ÷ pre-auths).
- **Un-converted pre-auths** — pre-auths with NO claim raised yet (anti-join).
- **Approved pre-auths that converted** — filter on pre-auth outcome AND a claim exists.
- **Pre-auth approved vs claim approved** side by side per case.
- **Settlement vs claim** reconciliation (needs settlement_item/settlement_batch cubes fleshed out).

Say the word to add the hub joins + these measures.
