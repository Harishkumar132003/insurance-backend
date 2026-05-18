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
    # Idempotent: on some environments the column was created outside alembic
    # (an earlier Base.metadata.create_all run) before this migration existed,
    # so a plain ADD COLUMN would explode with DuplicateColumn. Skip whatever
    # already matches the desired state and only create what's missing.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('claim_case_documents')}
    if 'document_type' not in existing_cols:
        op.add_column(
            'claim_case_documents',
            sa.Column('document_type', sa.String(), nullable=True),
        )
    existing_idx = {i['name'] for i in insp.get_indexes('claim_case_documents')}
    if 'ix_claim_case_documents_document_type' not in existing_idx:
        op.create_index(
            'ix_claim_case_documents_document_type',
            'claim_case_documents',
            ['claim_case_id', 'document_type'],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_idx = {i['name'] for i in insp.get_indexes('claim_case_documents')}
    if 'ix_claim_case_documents_document_type' in existing_idx:
        op.drop_index('ix_claim_case_documents_document_type', table_name='claim_case_documents')
    existing_cols = {c['name'] for c in insp.get_columns('claim_case_documents')}
    if 'document_type' in existing_cols:
        op.drop_column('claim_case_documents', 'document_type')
