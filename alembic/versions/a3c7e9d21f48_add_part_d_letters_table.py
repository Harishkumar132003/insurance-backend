"""add part_d_letters table

Revision ID: a3c7e9d21f48
Revises: f49b5a8c2e63
Create Date: 2026-05-11 11:30:26.398294

Persists the editable Part-D (Cashless Authorization Letter) field values so
the provider doesn't re-type the bill breakdown / authorization summary every
time they open the modal. One row per approval-round email
(claim_case_email_id is unique); attachment_id points at the rendered PDF.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'a3c7e9d21f48'
down_revision: Union[str, None] = 'f49b5a8c2e63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    # Idempotent: a previous interrupted run may have already created the table
    # without recording the revision. Skip creation if it's already there.
    if 'part_d_letters' in inspector.get_table_names():
        return

    op.create_table(
        'part_d_letters',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column('claim_case_id', UUID(as_uuid=True), sa.ForeignKey('claim_cases.id'), nullable=False),
        sa.Column('claim_case_email_id', sa.BigInteger, sa.ForeignKey('claim_case_emails.id'), nullable=False),
        sa.Column('attachment_id', sa.BigInteger, sa.ForeignKey('claim_case_email_attachments.id'), nullable=True),
        # header overrides — mirror the claim, but frozen on the letter
        sa.Column('approved_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('claim_number', sa.String, nullable=True),
        # bill breakdown — free text ("Rs.5,000/day", "Package", "N/A")
        sa.Column('room_rent_per_day', sa.String, nullable=True),
        sa.Column('icu_rent_per_day', sa.String, nullable=True),
        sa.Column('nursing_charges_per_day', sa.String, nullable=True),
        sa.Column('consultant_visit_charges_per_day', sa.String, nullable=True),
        sa.Column('surgeon_anesthetist_fee', sa.String, nullable=True),
        sa.Column('others', sa.String, nullable=True),
        # authorization summary — free text
        sa.Column('total_bill_amount', sa.String, nullable=True),
        sa.Column('deductions_detail', sa.String, nullable=True),
        sa.Column('discount', sa.String, nullable=True),
        sa.Column('co_pay', sa.String, nullable=True),
        sa.Column('deductibles', sa.String, nullable=True),
        sa.Column('total_authorised_amount', sa.String, nullable=True),
        sa.Column('amount_to_be_paid_by_insured', sa.String, nullable=True),
        sa.Column('remarks', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint('claim_case_email_id', name='uq_part_d_letter_email'),
    )
    op.create_index('ix_part_d_letters_claim_case_id', 'part_d_letters', ['claim_case_id'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'part_d_letters' not in inspector.get_table_names():
        return
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('part_d_letters')}
    if 'ix_part_d_letters_claim_case_id' in existing_indexes:
        op.drop_index('ix_part_d_letters_claim_case_id', table_name='part_d_letters')
    op.drop_table('part_d_letters')
