"""add policy_number extraction to policy summary prompts

Revision ID: b1f9e2d4c736
Revises: a30a9ef2a62c
Create Date: 2026-05-07 20:04:08.032471

The /run-policy endpoint now requires `policy_number` in the strict JSON
schema. Refresh the two prompt templates so the model is told to extract
the policy number from the file (or the workflow response) and to return
null when no policy number is present.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1f9e2d4c736'
down_revision: Union[str, None] = 'a30a9ef2a62c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POLICY_SUMMARY_PROMPT = """\
You are reviewing an Indian health-insurance policy.

Produce ONE JSON object with four fields: `summary`, `policy_number`,
`chronic_conditions`, `cost_estimates`.

1. `summary` — a concise plain-language summary of the policy. Include the sum
   insured, key coverage details, waiting periods, major exclusions,
   approval / rejection indicators, and any notable amounts or dates.

2. `policy_number` — the policy number printed on the document (e.g.
   "POL-2024-12345", "P/123456/01/2024"). Search the attached file context
   first; if absent, fall back to the workflow response JSON. Return null if
   no policy number is present.

3. `chronic_conditions` — for EACH listed condition, return a SHORT SENTENCE
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

4. `cost_estimates` — expected or sub-limit amounts the policy specifies for
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

Produce ONE JSON object with four fields: `summary`, `policy_number`,
`chronic_conditions`, `cost_estimates`.

1. `summary` — a concise plain-language summary of the policy covering the
   sum insured, coverage details, waiting periods, major exclusions, and any
   notable amounts or dates.

2. `policy_number` — the policy number printed on the document (e.g.
   "POL-2024-12345", "P/123456/01/2024"). Return null if no policy number is
   present.

3. `chronic_conditions` — for EACH listed condition, return a SHORT SENTENCE
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

4. `cost_estimates` — expected or sub-limit amounts the policy specifies for
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


# Snapshot of the previous (pre-this-migration) prompts so downgrade restores
# the three-field shape. Edits made manually after the prior migration ran
# will be lost on downgrade.
LEGACY_POLICY_SUMMARY_PROMPT = """\
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


LEGACY_POLICY_SUMMARY_FILE_ONLY_PROMPT = """\
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
    _set(conn, "policy-summary", LEGACY_POLICY_SUMMARY_PROMPT)
    _set(conn, "policy-summary-file-only", LEGACY_POLICY_SUMMARY_FILE_ONLY_PROMPT)
