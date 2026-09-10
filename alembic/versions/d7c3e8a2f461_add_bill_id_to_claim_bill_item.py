"""add bill_id to claim_bill_item (per-line hospital bill reference)

Each Raise Claim line can now carry the hospital's own bill / invoice reference,
so a provider reconciling a claim can tie a line back to the paper bill it came
from. Free text: hospitals number bills in their own formats, and several lines
routinely share one bill.

Nullable even though the form requires it — claims raised before this column
existed have no reference to backfill, and NOT NULL would fail on them.

Revision ID: d7c3e8a2f461
Revises: f4a8c1e7b309
Create Date: 2026-09-07
"""
import sqlalchemy as sa
from alembic import op

revision = 'd7c3e8a2f461'
down_revision = 'f4a8c1e7b309'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('claim_bill_item', sa.Column('bill_id', sa.String(), nullable=True))


def downgrade():
    op.drop_column('claim_bill_item', 'bill_id')
