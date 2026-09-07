"""rename claims.claim_case_id -> hospitalization_id

Renames only the claims FK column (+ its FK and unique constraints) for clearer
naming. The ORM keeps the attribute `claim_case_id` mapped to the new column, so
app code is unchanged; raw SQL / AI docs updated separately.

Revision ID: e2a6c9b4f1d7
Revises: d1f5b8c3a7e2
Create Date: 2026-06-26
"""
from alembic import op

revision = 'e2a6c9b4f1d7'
down_revision = 'd1f5b8c3a7e2'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('claims', 'claim_case_id', new_column_name='hospitalization_id')
    op.execute("ALTER TABLE claims RENAME CONSTRAINT claims_claim_case_id_fkey TO claims_hospitalization_id_fkey")
    op.execute("ALTER TABLE claims RENAME CONSTRAINT claims_claim_case_id_key TO claims_hospitalization_id_key")
    op.execute("ALTER INDEX IF EXISTS ix_claims_claim_case_id RENAME TO ix_claims_hospitalization_id")


def downgrade():
    op.execute("ALTER INDEX IF EXISTS ix_claims_hospitalization_id RENAME TO ix_claims_claim_case_id")
    op.execute("ALTER TABLE claims RENAME CONSTRAINT claims_hospitalization_id_key TO claims_claim_case_id_key")
    op.execute("ALTER TABLE claims RENAME CONSTRAINT claims_hospitalization_id_fkey TO claims_claim_case_id_fkey")
    op.alter_column('claims', 'hospitalization_id', new_column_name='claim_case_id')
