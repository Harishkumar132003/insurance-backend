"""add sent_email_id to claim_case_documents

Revision ID: b8d4f1a39c52
Revises: a3c7e9d21f48
Create Date: 2026-05-11 16:18:58.576470

Tracks which ClaimCaseDocument files have already been attached to an
outbound email, so follow-up emails (e.g. an ADR response) don't re-attach
documents that went out with an earlier submission. NULL = uploaded but not
yet sent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d4f1a39c52'
down_revision: Union[str, None] = 'a3c7e9d21f48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'claim_case_documents',
        sa.Column('sent_email_id', sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        'fk_claim_case_documents_sent_email_id',
        'claim_case_documents', 'claim_case_emails',
        ['sent_email_id'], ['id'],
    )
    op.create_index(
        'ix_claim_case_documents_sent_email_id',
        'claim_case_documents',
        ['sent_email_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_claim_case_documents_sent_email_id', table_name='claim_case_documents')
    op.drop_constraint('fk_claim_case_documents_sent_email_id', 'claim_case_documents', type_='foreignkey')
    op.drop_column('claim_case_documents', 'sent_email_id')
