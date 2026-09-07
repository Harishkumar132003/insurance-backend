"""drop the deprecated settlements table

Settlements are handled by settlement_batch + settlement_item; the old singular
`settlements` table is empty and unused. Dropping it (its FK/unique/RLS policy go
with it). Nothing references it.

Revision ID: d7b3f1c9a2e4
Revises: c4f8a1b6e2d3
Create Date: 2026-07-01
"""
import sqlalchemy as sa
from alembic import op

revision = 'd7b3f1c9a2e4'
down_revision = 'c4f8a1b6e2d3'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('settlements')


def downgrade():
    op.create_table(
        'settlements',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('claim_id', sa.BigInteger(), sa.ForeignKey('claims.id'), unique=True, nullable=False),
        sa.Column('settled_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='INITIATED'),
        sa.Column('settlement_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
