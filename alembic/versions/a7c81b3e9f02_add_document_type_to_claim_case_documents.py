"""add document_type to claim_case_documents

Revision ID: a7c81b3e9f02
Revises: fe67e403dd8c
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c81b3e9f02'
down_revision: Union[str, None] = 'fe67e403dd8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'claim_case_documents',
        sa.Column('document_type', sa.String(), nullable=True),
    )
    op.create_index(
        'ix_claim_case_documents_document_type',
        'claim_case_documents',
        ['claim_case_id', 'document_type'],
    )


def downgrade() -> None:
    op.drop_index('ix_claim_case_documents_document_type', table_name='claim_case_documents')
    op.drop_column('claim_case_documents', 'document_type')
