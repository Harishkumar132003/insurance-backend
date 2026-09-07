"""rename pre_auth_patient table to patient_personal_detail

Pure rename of the table (and its named index + hospitalization FK) for clarity.
Columns, data, and the model class (PreAuthPatient) are unchanged.

Revision ID: a9c2e5f7b1d4
Revises: f8b2d5c1a3e6
Create Date: 2026-06-26
"""
from alembic import op

revision = 'a9c2e5f7b1d4'
down_revision = 'f8b2d5c1a3e6'
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table('pre_auth_patient', 'patient_personal_detail')
    op.execute("ALTER INDEX IF EXISTS ix_pre_auth_patient_form_data_id "
               "RENAME TO ix_patient_personal_detail_form_data_id")
    op.execute("ALTER TABLE patient_personal_detail "
               "RENAME CONSTRAINT fk_pre_auth_patient_hospitalization "
               "TO fk_patient_personal_detail_hospitalization")


def downgrade():
    op.execute("ALTER TABLE patient_personal_detail "
               "RENAME CONSTRAINT fk_patient_personal_detail_hospitalization "
               "TO fk_pre_auth_patient_hospitalization")
    op.execute("ALTER INDEX IF EXISTS ix_patient_personal_detail_form_data_id "
               "RENAME TO ix_pre_auth_patient_form_data_id")
    op.rename_table('patient_personal_detail', 'pre_auth_patient')
