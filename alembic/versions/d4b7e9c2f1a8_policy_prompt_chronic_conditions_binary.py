"""policy prompt: chronic_conditions binary true/false

Revision ID: d4b7e9c2f1a8
Revises: c8e5a1f9b2d7
Create Date: 2026-04-21 00:45:00.000000

Tighten the policy-summary prompts so chronic_conditions fields are a strict
boolean (no null). Tells the model to default to `true` when PED is covered
and the condition is not explicitly excluded; otherwise `false`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4b7e9c2f1a8'
down_revision: Union[str, None] = 'c8e5a1f9b2d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POLICY_SUMMARY_PROMPT = """\
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


POLICY_SUMMARY_FILE_ONLY_PROMPT = """\
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


# Previous prompts (from c8e5a1f9b2d7) for downgrade.
PREV_POLICY_SUMMARY_PROMPT = """\
You are reviewing an Indian health-insurance policy.

Produce ONE JSON object with two fields:

1. `summary` — a concise plain-language summary of the policy. Include the sum
   insured, key coverage details, waiting periods, major exclusions,
   approval / rejection indicators, and any notable amounts or dates.

2. `chronic_conditions` — for each listed chronic condition, decide whether
   THIS policy covers it. Rules for every field:
     - `true`  → the policy clearly covers the condition. A waiting period
                 STILL counts as covered.
     - `false` → the policy explicitly excludes the condition.
     - `null`  → the document does not mention the condition, or the coverage
                 is unclear.

   Fields (use snake_case, return all of them):
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

2. `chronic_conditions` — for each listed chronic condition, decide whether
   THIS policy covers it. Rules for every field:
     - `true`  → the policy clearly covers the condition. A waiting period
                 STILL counts as covered.
     - `false` → the policy explicitly excludes the condition.
     - `null`  → the document does not mention the condition, or the coverage
                 is unclear.

   Fields (use snake_case, return all of them):
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
