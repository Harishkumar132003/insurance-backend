"""add form_values to claim_case_emails

Revision ID: d52e3c8a417b
Revises: c4a8e1f2d935
Create Date: 2026-05-08 00:01:21.798483

Captures the structured form payload the hospital submitted alongside the
rendered email body, so the onboarded-provider UI can render a structured
form view instead of the rendered HTML body.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd52e3c8a417b'
down_revision: Union[str, None] = 'c4a8e1f2d935'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'claim_case_emails',
        sa.Column('form_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('claim_case_emails', 'form_values')
