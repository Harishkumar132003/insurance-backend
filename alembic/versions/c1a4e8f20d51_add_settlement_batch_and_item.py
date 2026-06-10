"""add settlement_batch and settlement_item

Batch settlement / remittance-advice tables. `settlement_batch` holds the
header parsed from an uploaded insurer payment document; `settlement_item`
holds one row per claim, linked to `hospitalization` via claim_number at save
time. Independent of the existing per-claim `settlements` table.

Revision ID: c1a4e8f20d51
Revises: b9d3f7a21c84
Create Date: 2026-06-09 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'c1a4e8f20d51'
down_revision: Union[str, None] = 'b9d3f7a21c84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'settlement_batch',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('hospital_id', UUID(as_uuid=True), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('tpa_insurer', sa.String(), nullable=True),
        sa.Column('total_settlement_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('payment_mode', sa.String(), nullable=True),
        sa.Column('payment_batch', sa.String(), nullable=True),
        sa.Column('utr_number', sa.String(), nullable=True),
        sa.Column('settlement_number', sa.String(), nullable=True),
        sa.Column('settlement_date', sa.Date(), nullable=True),
        sa.Column('hospital_account_number', sa.String(), nullable=True),
        sa.Column('source_original_filename', sa.String(), nullable=True),
        sa.Column('source_stored_filename', sa.String(), nullable=True),
        sa.Column('source_file_path', sa.String(), nullable=True),
        sa.Column('source_content_type', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_settlement_batch_hospital_id', 'settlement_batch', ['hospital_id'])

    op.create_table(
        'settlement_item',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('batch_id', UUID(as_uuid=True),
                  sa.ForeignKey('settlement_batch.id', ondelete='CASCADE'), nullable=False),
        sa.Column('claim_number', sa.String(), nullable=True),
        sa.Column('settled_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('claim_raised_amount', sa.Numeric(14, 2), nullable=True),
        sa.Column('disallowance', sa.Numeric(14, 2), nullable=True),
        sa.Column('disallowance_reason', sa.String(), nullable=True),
        sa.Column('claim_case_id', UUID(as_uuid=True),
                  sa.ForeignKey('hospitalization.id'), nullable=True),
        sa.Column('is_matched', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_settlement_item_batch_id', 'settlement_item', ['batch_id'])
    op.create_index('ix_settlement_item_claim_case_id', 'settlement_item', ['claim_case_id'])
    op.create_index('ix_settlement_item_claim_number', 'settlement_item', ['claim_number'])


def downgrade() -> None:
    op.drop_index('ix_settlement_item_claim_number', table_name='settlement_item')
    op.drop_index('ix_settlement_item_claim_case_id', table_name='settlement_item')
    op.drop_index('ix_settlement_item_batch_id', table_name='settlement_item')
    op.drop_table('settlement_item')
    op.drop_index('ix_settlement_batch_hospital_id', table_name='settlement_batch')
    op.drop_table('settlement_batch')
