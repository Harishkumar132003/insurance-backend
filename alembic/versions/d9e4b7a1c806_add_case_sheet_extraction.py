"""add case_sheet_extraction

Revision ID: d9e4b7a1c806
Revises: c5e9a2b6d3f8
Create Date: 2026-08-03

Stores an uploaded case sheet alongside what the AI pulled out of it: the flat
field values that pre-filled the form, a per-field confidence (EASY/MEDIUM/HARD)
and the verbatim source fragment each value came from, plus the repeatable
treatment/investigation payloads for audit.

The row is created at extract time, before a claim case exists, so
`claim_case_id` is nullable and is filled in when the form is first saved.

Idempotent: app startup runs Base.metadata.create_all, which may already have
created the table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = 'd9e4b7a1c806'
down_revision: Union[str, None] = 'c5e9a2b6d3f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'case_sheet_extraction' in insp.get_table_names():
        return

    op.create_table(
        'case_sheet_extraction',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('hospital_id', UUID(as_uuid=True),
                  sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('claim_case_id', UUID(as_uuid=True),
                  sa.ForeignKey('hospitalization.id'), nullable=True),
        sa.Column('original_filename', sa.String(), nullable=True),
        sa.Column('stored_filename', sa.String(), nullable=True),
        sa.Column('file_path', sa.String(), nullable=True),
        sa.Column('content_type', sa.String(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('extracted', JSONB(), nullable=True),
        sa.Column('field_meta', JSONB(), nullable=True),
        sa.Column('treatments', JSONB(), nullable=True),
        sa.Column('investigations', JSONB(), nullable=True),
        sa.Column('created_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_case_sheet_extraction_hospital_id',
                    'case_sheet_extraction', ['hospital_id'])
    op.create_index('ix_case_sheet_extraction_claim_case_id',
                    'case_sheet_extraction', ['claim_case_id'])


def downgrade() -> None:
    op.drop_index('ix_case_sheet_extraction_claim_case_id', table_name='case_sheet_extraction')
    op.drop_index('ix_case_sheet_extraction_hospital_id', table_name='case_sheet_extraction')
    op.drop_table('case_sheet_extraction')
