"""add approved_amount column to status_history (per-round amount)

Revision ID: a30a9ef2a62c
Revises: 76d71c22cdd5
Create Date: 2026-05-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a30a9ef2a62c'
down_revision: Union[str, None] = '76d71c22cdd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'status_history',
        sa.Column('approved_amount', sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('status_history', 'approved_amount')
