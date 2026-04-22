"""update policy-summary prompt for chronic conditions

Revision ID: c8e5a1f9b2d7
Revises: f7a3b2c9d1e4
Create Date: 2026-04-21 00:30:00.000000

The /run-policy endpoint now calls OpenAI with a strict JSON schema that
requires both `summary` and `chronic_conditions`. Refresh the two prompt
templates the code loads (`policy-summary` when a policy_id is present,
`policy-summary-file-only` when only a file is uploaded) so the prompt
describes the rules for every chronic-condition field.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8e5a1f9b2d7'
down_revision: Union[str, None] = 'f7a3b2c9d1e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POLICY_SUMMARY_PROMPT = """\
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


POLICY_SUMMARY_FILE_ONLY_PROMPT = """\
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


# Previous defaults (for downgrade). If an operator has edited the prompt
# manually, downgrade will still replace with this snapshot — there is no way
# to recover the edited text through the migration.
LEGACY_POLICY_SUMMARY_PROMPT = (
    "Summarize this policy workflow response in plain language. "
    "Keep it concise and include key policy details, approval/rejection indicators, "
    "and notable amounts or dates if present.\n\n"
    "Response JSON:\n{response_json}\n\n"
    "Attached file context:\n{file_context}"
)

LEGACY_POLICY_SUMMARY_FILE_ONLY_PROMPT = (
    "Summarize the attached policy document context in plain language. "
    "Keep it concise and include important coverage details, restrictions, waiting periods, "
    "and notable amounts or dates if present.\n\n"
    "Attached file context:\n{file_context}"
)


def _upsert(connection, key: str, prompt_text: str) -> None:
    result = connection.execute(
        sa.text("UPDATE summary_prompt_templates SET prompt_text = :p WHERE key = :k"),
        {"p": prompt_text, "k": key},
    )
    if result.rowcount == 0:
        connection.execute(
            sa.text(
                "INSERT INTO summary_prompt_templates (id, key, prompt_text) "
                "VALUES (gen_random_uuid(), :k, :p)"
            ),
            {"k": key, "p": prompt_text},
        )


def upgrade() -> None:
    conn = op.get_bind()
    _upsert(conn, "policy-summary", POLICY_SUMMARY_PROMPT)
    _upsert(conn, "policy-summary-file-only", POLICY_SUMMARY_FILE_ONLY_PROMPT)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE summary_prompt_templates SET prompt_text = :p WHERE key = :k"),
        {"p": LEGACY_POLICY_SUMMARY_PROMPT, "k": "policy-summary"},
    )
    conn.execute(
        sa.text("UPDATE summary_prompt_templates SET prompt_text = :p WHERE key = :k"),
        {"p": LEGACY_POLICY_SUMMARY_FILE_ONLY_PROMPT, "k": "policy-summary-file-only"},
    )
