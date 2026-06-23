"""add rate + days to claim_bill_item (per-day bill lines)

Adds claim_bill_item.rate and .days so per-day bill lines (e.g. Non ICU Room /
ICU Charges on the Raise Claim page) round-trip: amount == rate * days, and a
line is "per day" when rate is not NULL. Flat lines leave both NULL.

Revision ID: c5e9a2b6d3f8
Revises: b4d8f1c2e3a5
Create Date: 2026-06-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'c5e9a2b6d3f8'
down_revision = 'b4d8f1c2e3a5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('claim_bill_item', sa.Column('rate', sa.Numeric(12, 2), nullable=True))
    op.add_column('claim_bill_item', sa.Column('days', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('claim_bill_item', 'days')
    op.drop_column('claim_bill_item', 'rate')
