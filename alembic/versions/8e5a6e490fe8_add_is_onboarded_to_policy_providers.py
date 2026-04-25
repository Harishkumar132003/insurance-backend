"""add is_onboarded to policy_provider_configs

Revision ID: 8e5a6e490fe8
Revises: c6b4e7f2a9d3
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8e5a6e490fe8'
down_revision: Union[str, None] = 'c6b4e7f2a9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'policy_provider_configs',
        sa.Column(
            'is_onboarded',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('policy_provider_configs', 'is_onboarded')
