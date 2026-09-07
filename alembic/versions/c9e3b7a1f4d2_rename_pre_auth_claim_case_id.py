"""rename pre_auth.claim_case_id -> hospitalization_id

Renames only the pre_auth FK column (and its constraint) for clearer naming. The
ORM keeps the attribute `claim_case_id` mapped to the new column, so app code is
unchanged; raw SQL / AI docs updated separately. Other tables keep claim_case_id.

Revision ID: c9e3b7a1f4d2
Revises: b8d2f5a9c3e1
Create Date: 2026-06-26
"""
from alembic import op

revision = 'c9e3b7a1f4d2'
down_revision = 'b8d2f5a9c3e1'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('pre_auth', 'claim_case_id', new_column_name='hospitalization_id')
    op.execute("ALTER TABLE pre_auth RENAME CONSTRAINT form_data_claim_case_id_fkey "
               "TO pre_auth_hospitalization_id_fkey")


def downgrade():
    op.execute("ALTER TABLE pre_auth RENAME CONSTRAINT pre_auth_hospitalization_id_fkey "
               "TO form_data_claim_case_id_fkey")
    op.alter_column('pre_auth', 'hospitalization_id', new_column_name='claim_case_id')
