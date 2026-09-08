"""add zonal + co-pay disallowance to part_d_letters

The pre-auth approval could reduce what it authorised but never recorded WHY at
the bill level. This adds a zonal disallowance (treatment taken outside the
policy's zone) and attaches a reason to it and to the existing co-pay figure.

`as_co_pay` is reused rather than replaced: the Authorisation Summary's old flat
"Co-Pay" field is being relabelled "Co-pay Disallowance", and the column has
never been written (null/0 in every existing row), so nothing is reinterpreted.

All nullable — existing letters have no disallowances to backfill.

Revision ID: e8b4d2f9a370
Revises: d7c3e8a2f461
Create Date: 2026-09-08
"""
import sqlalchemy as sa
from alembic import op

revision = 'e8b4d2f9a370'
down_revision = 'd7c3e8a2f461'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('part_d_letters', sa.Column('as_zonal', sa.Numeric(12, 2), nullable=True))
    op.add_column('part_d_letters', sa.Column('zonal_reason', sa.String(), nullable=True))
    op.add_column('part_d_letters', sa.Column('co_pay_reason', sa.String(), nullable=True))


def downgrade():
    op.drop_column('part_d_letters', 'co_pay_reason')
    op.drop_column('part_d_letters', 'zonal_reason')
    op.drop_column('part_d_letters', 'as_zonal')
