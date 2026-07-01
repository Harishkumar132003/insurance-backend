"""add uhid + claim_number to claims

Denormalised convenience columns on the claims row, sourced from the case
(hospitalization). Set by the app on claim raise; backfilled from existing data.

Revision ID: d1f5b8c3a7e2
Revises: c9e3b7a1f4d2
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op

revision = 'd1f5b8c3a7e2'
down_revision = 'c9e3b7a1f4d2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('claims', sa.Column('uhid', sa.String(), nullable=True))
    op.add_column('claims', sa.Column('claim_number', sa.String(), nullable=True))
    op.execute("""
        UPDATE claims c
           SET uhid = h.uhid,
               claim_number = h.claim_number
          FROM hospitalization h
         WHERE h.id = c.claim_case_id
    """)


def downgrade():
    op.drop_column('claims', 'claim_number')
    op.drop_column('claims', 'uhid')
