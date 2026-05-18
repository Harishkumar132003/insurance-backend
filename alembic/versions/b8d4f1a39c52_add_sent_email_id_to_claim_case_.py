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
    # Idempotent — schema may already be at this state from an out-of-band
    # create_all on production.
    bind = op.get_bind()
    insp = sa.inspect(bind)

    cols = {c['name'] for c in insp.get_columns('claim_case_documents')}
    if 'sent_email_id' not in cols:
        op.add_column(
            'claim_case_documents',
            sa.Column('sent_email_id', sa.BigInteger(), nullable=True),
        )

    fks = {fk['name'] for fk in insp.get_foreign_keys('claim_case_documents')}
    if 'fk_claim_case_documents_sent_email_id' not in fks:
        op.create_foreign_key(
            'fk_claim_case_documents_sent_email_id',
            'claim_case_documents', 'claim_case_emails',
            ['sent_email_id'], ['id'],
        )

    idx = {i['name'] for i in insp.get_indexes('claim_case_documents')}
    if 'ix_claim_case_documents_sent_email_id' not in idx:
        op.create_index(
            'ix_claim_case_documents_sent_email_id',
            'claim_case_documents',
            ['sent_email_id'],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    idx = {i['name'] for i in insp.get_indexes('claim_case_documents')}
    if 'ix_claim_case_documents_sent_email_id' in idx:
        op.drop_index('ix_claim_case_documents_sent_email_id', table_name='claim_case_documents')

    fks = {fk['name'] for fk in insp.get_foreign_keys('claim_case_documents')}
    if 'fk_claim_case_documents_sent_email_id' in fks:
        op.drop_constraint('fk_claim_case_documents_sent_email_id', 'claim_case_documents', type_='foreignkey')

    cols = {c['name'] for c in insp.get_columns('claim_case_documents')}
    if 'sent_email_id' in cols:
        op.drop_column('claim_case_documents', 'sent_email_id')
