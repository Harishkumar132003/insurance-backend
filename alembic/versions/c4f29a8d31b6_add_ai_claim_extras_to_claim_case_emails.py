"""add ai_approved_breakdown and ai_denial_reason to claim_case_emails

Merges the two outstanding heads and adds the new claim-stage AI-extraction
columns.

Revision ID: c4f29a8d31b6
Revises: b3a1d52ef817, b8d4f1a39c52
Create Date: 2026-05-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c4f29a8d31b6'
down_revision: Union[str, Sequence[str], None] = ('b3a1d52ef817', 'b8d4f1a39c52')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent — columns may already exist from an out-of-band create_all.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('claim_case_emails')}
    if 'ai_approved_breakdown' not in cols:
        op.add_column(
            'claim_case_emails',
            sa.Column('ai_approved_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    if 'ai_denial_reason' not in cols:
        op.add_column(
            'claim_case_emails',
            sa.Column('ai_denial_reason', sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('claim_case_emails')}
    if 'ai_denial_reason' in cols:
        op.drop_column('claim_case_emails', 'ai_denial_reason')
    if 'ai_approved_breakdown' in cols:
        op.drop_column('claim_case_emails', 'ai_approved_breakdown')
