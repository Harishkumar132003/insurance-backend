"""drop claimed_amount + remarks from pre_auth

claimed_amount was redundant — the claim total is derived from claim_bill_item
lines and stored on the claims row. remarks moves to a dedicated claim tracking
table (forthcoming); the raise-time remark still flows into the claim email and
status_history. Both columns are removed here.

Revision ID: b8d2f5a9c3e1
Revises: a7c1e4b8d2f5
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op

revision = 'b8d2f5a9c3e1'
down_revision = 'a7c1e4b8d2f5'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('pre_auth', 'remarks')
    op.drop_column('pre_auth', 'claimed_amount')


def downgrade():
    op.add_column('pre_auth', sa.Column('claimed_amount', sa.Numeric(12, 2), nullable=True))
    op.add_column('pre_auth', sa.Column('remarks', sa.Text(), nullable=True))
    # Best-effort: restore claimed_amount on claim forms from their bill lines.
    op.execute("""
        UPDATE pre_auth p
           SET claimed_amount = s.total
          FROM (SELECT form_data_id, SUM(amount) AS total
                  FROM claim_bill_item GROUP BY form_data_id) s
         WHERE s.form_data_id = p.id
    """)
