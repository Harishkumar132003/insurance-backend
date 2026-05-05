"""add documents_list jsonb columns to query_logs and claim_case_emails

Revision ID: 76d71c22cdd5
Revises: fc6ccd7f820b
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '76d71c22cdd5'
down_revision: Union[str, None] = 'fc6ccd7f820b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'query_logs',
        sa.Column('documents_list', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'claim_case_emails',
        sa.Column('ai_documents_list', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('claim_case_emails', 'ai_documents_list')
    op.drop_column('query_logs', 'documents_list')
