"""add uhid + hospitalization_id to pre_auth_patient

Denormalised convenience columns on the patient row, sourced from the case
(hospitalization) via the form row. Backfilled from existing data; kept current
by the app on form save.

Revision ID: f8b2d5c1a3e6
Revises: e7a1c4b9d2f0
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'f8b2d5c1a3e6'
down_revision = 'e7a1c4b9d2f0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('pre_auth_patient', sa.Column('hospitalization_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('pre_auth_patient', sa.Column('uhid', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_pre_auth_patient_hospitalization', 'pre_auth_patient',
        'hospitalization', ['hospitalization_id'], ['id'],
    )
    # Backfill from the case via the form row.
    op.execute("""
        UPDATE pre_auth_patient pp
           SET hospitalization_id = f.claim_case_id,
               uhid = h.uhid
          FROM pre_auth f
          JOIN hospitalization h ON h.id = f.claim_case_id
         WHERE f.id = pp.form_data_id
    """)


def downgrade():
    op.drop_constraint('fk_pre_auth_patient_hospitalization', 'pre_auth_patient', type_='foreignkey')
    op.drop_column('pre_auth_patient', 'uhid')
    op.drop_column('pre_auth_patient', 'hospitalization_id')
