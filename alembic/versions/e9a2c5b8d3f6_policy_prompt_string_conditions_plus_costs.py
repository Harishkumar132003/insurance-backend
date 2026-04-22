"""policy prompt: string chronic_conditions + cost_estimates section

Revision ID: e9a2c5b8d3f6
Revises: d4b7e9c2f1a8
Create Date: 2026-04-21 01:00:00.000000

- chronic_conditions values are now sentence-style strings (not booleans).
- Adds a new `cost_estimates` section covering room_rent, investigation_cost,
  icu_charges, ot_charges, professional_fees, medicines_cost, other_expenses,
  package_charges, total_cost — each a short string or null.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9a2c5b8d3f6'
down_revision: Union[str, None] = 'd4b7e9c2f1a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POLICY_SUMMARY_PROMPT = """\
You are reviewing an Indian health-insurance policy.

Produce ONE JSON object with three fields: `summary`, `chronic_conditions`,
`cost_estimates`.

1. `summary` — a concise plain-language summary of the policy. Include the sum
   insured, key coverage details, waiting periods, major exclusions,
   approval / rejection indicators, and any notable amounts or dates.

2. `chronic_conditions` — for EACH listed condition, return a SHORT SENTENCE
   (string) describing how this policy treats the condition. Mention whether
   it is covered, any waiting period, sub-limits, co-pay, or whether it is
   explicitly excluded. If the document is silent, say so and note whether
   Pre-Existing Diseases are covered in general. Never return null or a
   boolean.

   Fields (use snake_case, return all of them as strings):
     diabetes, heart_disease, hypertension, hyperlipidemia, osteoarthritis,
     asthma_copd, cancer, alcohol_drug_abuse, hiv_std

   `other` — a short free-text description of any ADDITIONAL chronic condition
   the policy explicitly mentions (e.g. "Chronic kidney disease — 24 month
   waiting period"), or null if none.

3. `cost_estimates` — expected or sub-limit amounts the policy specifies for
   each cost head. Return a short string (e.g. "₹5,000 per day",
   "1% of sum insured", "No sub-limit"). Use null if the document does not
   mention the head.

   Fields (all required, string or null):
     room_rent, investigation_cost, icu_charges, ot_charges,
     professional_fees, medicines_cost, other_expenses, package_charges,
     total_cost

Workflow response JSON:
{response_json}

Attached policy document:
{file_context}
"""


POLICY_SUMMARY_FILE_ONLY_PROMPT = """\
You are reviewing an Indian health-insurance policy document.

Produce ONE JSON object with three fields: `summary`, `chronic_conditions`,
`cost_estimates`.

1. `summary` — a concise plain-language summary of the policy covering the
   sum insured, coverage details, waiting periods, major exclusions, and any
   notable amounts or dates.

2. `chronic_conditions` — for EACH listed condition, return a SHORT SENTENCE
   (string) describing how this policy treats the condition. Mention whether
   it is covered, any waiting period, sub-limits, co-pay, or whether it is
   explicitly excluded. If the document is silent, say so and note whether
   Pre-Existing Diseases are covered in general. Never return null or a
   boolean.

   Fields (use snake_case, return all of them as strings):
     diabetes, heart_disease, hypertension, hyperlipidemia, osteoarthritis,
     asthma_copd, cancer, alcohol_drug_abuse, hiv_std

   `other` — a short free-text description of any ADDITIONAL chronic condition
   the policy explicitly mentions (e.g. "Chronic kidney disease — 24 month
   waiting period"), or null if none.

3. `cost_estimates` — expected or sub-limit amounts the policy specifies for
   each cost head. Return a short string (e.g. "₹5,000 per day",
   "1% of sum insured", "No sub-limit"). Use null if the document does not
   mention the head.

   Fields (all required, string or null):
     room_rent, investigation_cost, icu_charges, ot_charges,
     professional_fees, medicines_cost, other_expenses, package_charges,
     total_cost

Attached policy document:
{file_context}
"""


PREV_POLICY_SUMMARY_PROMPT = """\
You are reviewing an Indian health-insurance policy.

Produce ONE JSON object with two fields:

1. `summary` — a concise plain-language summary of the policy. Include the sum
   insured, key coverage details, waiting periods, major exclusions,
   approval / rejection indicators, and any notable amounts or dates.

2. `chronic_conditions` — for each listed chronic condition, return a BOOLEAN:
     - `true`  → the policy covers the condition. Treat the following as COVERED:
                 explicitly listed as covered, covered under Pre-Existing Disease
                 (PED) with or without a waiting period, or covered after a
                 specified-disease waiting period.
     - `false` → the policy does NOT cover the condition. Treat as NOT COVERED:
                 explicitly excluded, or listed as a permanent exclusion.

   When the document is silent on a condition, DEFAULT TO `true` if the policy
   covers Pre-Existing Diseases in general; otherwise default to `false`.
   Never return null.

   Fields (use snake_case, return all of them as boolean):
     diabetes, heart_disease, hypertension, hyperlipidemia, osteoarthritis,
     asthma_copd, cancer, alcohol_drug_abuse, hiv_std

   `other` — a short free-text description of any ADDITIONAL chronic condition
   the policy explicitly mentions (e.g. "Chronic kidney disease — 24 month
   waiting period"), or null if none.

Workflow response JSON:
{response_json}

Attached policy document:
{file_context}
"""


PREV_POLICY_SUMMARY_FILE_ONLY_PROMPT = """\
You are reviewing an Indian health-insurance policy document.

Produce ONE JSON object with two fields:

1. `summary` — a concise plain-language summary of the policy covering the
   sum insured, coverage details, waiting periods, major exclusions, and any
   notable amounts or dates.

2. `chronic_conditions` — for each listed chronic condition, return a BOOLEAN:
     - `true`  → the policy covers the condition. Treat the following as COVERED:
                 explicitly listed as covered, covered under Pre-Existing Disease
                 (PED) with or without a waiting period, or covered after a
                 specified-disease waiting period.
     - `false` → the policy does NOT cover the condition. Treat as NOT COVERED:
                 explicitly excluded, or listed as a permanent exclusion.

   When the document is silent on a condition, DEFAULT TO `true` if the policy
   covers Pre-Existing Diseases in general; otherwise default to `false`.
   Never return null.

   Fields (use snake_case, return all of them as boolean):
     diabetes, heart_disease, hypertension, hyperlipidemia, osteoarthritis,
     asthma_copd, cancer, alcohol_drug_abuse, hiv_std

   `other` — a short free-text description of any ADDITIONAL chronic condition
   the policy explicitly mentions (e.g. "Chronic kidney disease — 24 month
   waiting period"), or null if none.

Attached policy document:
{file_context}
"""


def _set(connection, key: str, prompt_text: str) -> None:
    connection.execute(
        sa.text("UPDATE summary_prompt_templates SET prompt_text = :p WHERE key = :k"),
        {"p": prompt_text, "k": key},
    )


def upgrade() -> None:
    conn = op.get_bind()
    _set(conn, "policy-summary", POLICY_SUMMARY_PROMPT)
    _set(conn, "policy-summary-file-only", POLICY_SUMMARY_FILE_ONLY_PROMPT)


def downgrade() -> None:
    conn = op.get_bind()
    _set(conn, "policy-summary", PREV_POLICY_SUMMARY_PROMPT)
    _set(conn, "policy-summary-file-only", PREV_POLICY_SUMMARY_FILE_ONLY_PROMPT)
