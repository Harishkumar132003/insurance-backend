"""add numeric bill-breakdown + authorisation-summary columns to part_d_letters

Adds numeric columns to part_d_letters so the Part-D "Review & Approve" modal can
mirror the pre-auth cost estimates (room rent, ICU, investigation, OT, professional
fees, medicines, package, others) and auto-compute the authorisation summary.
bd_room_rent / bd_icu_charges are per-day rates multiplied by the stored day counts.
total_authorised == approved_amount, so it is NOT duplicated here. The legacy
free-text bill/summary columns are left in place (unused) for backward compat.

Revision ID: b4d8f1c2e3a5
Revises: a3c7e9b1d2f4
Create Date: 2026-06-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'b4d8f1c2e3a5'
down_revision = 'a3c7e9b1d2f4'
branch_labels = None
depends_on = None


_NUMERIC_COLS = [
    'bd_room_rent',
    'bd_icu_charges',
    'bd_investigation_cost',
    'bd_ot_charges',
    'bd_professional_fees',
    'bd_medicines_cost',
    'bd_package_charges',
    'bd_other_expenses',
    'as_total_bill_amount',
    'as_discount',
    'as_co_pay',
    'as_deductibles',
    'as_deductions',
    'as_amount_to_be_paid_by_insured',
]


def upgrade():
    for col in _NUMERIC_COLS:
        op.add_column('part_d_letters', sa.Column(col, sa.Numeric(12, 2), nullable=True))
    op.add_column('part_d_letters', sa.Column('bd_expected_days', sa.BigInteger(), nullable=True))
    op.add_column('part_d_letters', sa.Column('bd_icu_days', sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column('part_d_letters', 'bd_icu_days')
    op.drop_column('part_d_letters', 'bd_expected_days')
    for col in reversed(_NUMERIC_COLS):
        op.drop_column('part_d_letters', col)
