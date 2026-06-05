"""rename hospitalization.status -> case_status and claim_status -> preauth_outcome

Pure column rename on the `hospitalization` table (model ClaimCase). No value
changes. The new names disambiguate the two columns (the old `claim_status`
misleadingly implied the claim-stage outcome, which actually lives in
`case_status` as the CLAIM_* values). The API/JSON contract is unchanged —
schemas/claim_case.py keeps the `status` / `claim_status` response keys via
validation_alias.

Revision ID: b9d3f7a21c84
Revises: d7f3a1c9b204
Create Date: 2026-06-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b9d3f7a21c84'
down_revision: Union[str, None] = 'd7f3a1c9b204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('hospitalization', 'status', new_column_name='case_status')
    op.alter_column('hospitalization', 'claim_status', new_column_name='preauth_outcome')


def downgrade() -> None:
    op.alter_column('hospitalization', 'case_status', new_column_name='status')
    op.alter_column('hospitalization', 'preauth_outcome', new_column_name='claim_status')
