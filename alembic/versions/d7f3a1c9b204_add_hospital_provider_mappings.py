"""add hospital_provider_mappings

Revision ID: d7f3a1c9b204
Revises: c4f29a8d31b6
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd7f3a1c9b204'
down_revision: Union[str, None] = 'c4f29a8d31b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent — the table may already exist from an out-of-band create_all.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'hospital_provider_mappings' in insp.get_table_names():
        return
    op.create_table(
        'hospital_provider_mappings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('hospital_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('policy_provider_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('policy_provider_configs.id'), nullable=False),
        sa.Column('room_charges', postgresql.JSONB(), nullable=True),
        sa.Column('extracted_data', postgresql.JSONB(), nullable=True),
        sa.Column('mou_original_filename', sa.String(), nullable=True),
        sa.Column('mou_stored_filename', sa.String(), nullable=True),
        sa.Column('mou_file_path', sa.String(), nullable=True),
        sa.Column('mou_content_type', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('hospital_id', 'policy_provider_id', name='uq_hospital_provider'),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'hospital_provider_mappings' in insp.get_table_names():
        op.drop_table('hospital_provider_mappings')
