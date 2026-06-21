"""rename pre_auth.status to draft_state

Renames the pre_auth (FormData) `status` column to `draft_state`. It only ever
holds the form lifecycle ('DRAFT' | 'SUBMITTED') and was being confused with the
case workflow status (hospitalization.case_status / preauth_outcome).

Revision ID: e1a2b3c4d5f6
Revises: d2b5f9c33e07
Create Date: 2026-06-19
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e1a2b3c4d5f6'
down_revision = 'd2b5f9c33e07'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('pre_auth', 'status', new_column_name='draft_state')


def downgrade():
    op.alter_column('pre_auth', 'draft_state', new_column_name='status')
