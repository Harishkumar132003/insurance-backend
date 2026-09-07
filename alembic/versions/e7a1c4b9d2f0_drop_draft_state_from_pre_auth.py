"""drop draft_state from pre_auth

The per-form draft/submitted flag is no longer stored. "Submitted" is now derived:
  • pre-auth form  → preauth_status != 'DRAFT'
  • claim form     → a (unique) claims row exists for the case

Revision ID: e7a1c4b9d2f0
Revises: d6f0b3c7e4a9
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op

revision = 'e7a1c4b9d2f0'
down_revision = 'd6f0b3c7e4a9'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('pre_auth', 'draft_state')


def downgrade():
    op.add_column(
        'pre_auth',
        sa.Column('draft_state', sa.String(), nullable=False, server_default='DRAFT'),
    )
    # Best-effort backfill of the restored flag from the derived signals.
    op.execute("""
        UPDATE pre_auth p SET draft_state = 'SUBMITTED'
         WHERE (p.stage = 'PRE_AUTH' AND p.preauth_status <> 'DRAFT')
            OR (p.stage = 'CLAIM'
                AND EXISTS (SELECT 1 FROM claims c WHERE c.claim_case_id = p.claim_case_id))
    """)
