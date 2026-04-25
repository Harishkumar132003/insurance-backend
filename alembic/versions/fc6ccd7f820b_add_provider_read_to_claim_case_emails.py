"""add provider_read to claim_case_emails

Revision ID: fc6ccd7f820b
Revises: 26807d186f87
Create Date: 2026-04-24 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'fc6ccd7f820b'
down_revision: Union[str, None] = '26807d186f87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'claim_case_emails',
        sa.Column(
            'provider_read',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column('claim_case_emails', 'provider_read')
