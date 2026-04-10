"""add_claim_case_documents_table

Revision ID: a1b2c3d4e5f6
Revises: be62375c984e
Create Date: 2026-04-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'be62375c984e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'claim_case_documents',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('claim_case_id', sa.BigInteger(), nullable=False),
        sa.Column('original_filename', sa.String(), nullable=False),
        sa.Column('stored_filename', sa.String(), nullable=False),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['claim_case_id'], ['claim_cases.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_claim_case_documents_claim_case_id', 'claim_case_documents', ['claim_case_id'])


def downgrade() -> None:
    op.drop_index('ix_claim_case_documents_claim_case_id', table_name='claim_case_documents')
    op.drop_table('claim_case_documents')
