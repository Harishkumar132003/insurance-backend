"""add form_type to form_templates

Revision ID: c4a8e1f2d935
Revises: b1f9e2d4c736
Create Date: 2026-05-07 21:55:39.364995

Adds a `form_type` discriminator (e.g. 'PRE_AUTH', 'FORM_C') so the same
table can hold multiple kinds of HTML/CSS templates per provider, and
widens the (name, version) uniqueness to include form_type so the same
name+version pair can exist for different form kinds.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4a8e1f2d935'
down_revision: Union[str, None] = 'b1f9e2d4c736'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'form_templates',
        sa.Column('form_type', sa.String(), nullable=False, server_default='PRE_AUTH'),
    )
    op.drop_constraint('uq_form_template_name_version', 'form_templates', type_='unique')
    op.create_unique_constraint(
        'uq_form_template_name_version_type',
        'form_templates',
        ['name', 'version', 'form_type'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_form_template_name_version_type', 'form_templates', type_='unique')
    op.create_unique_constraint(
        'uq_form_template_name_version',
        'form_templates',
        ['name', 'version'],
    )
    op.drop_column('form_templates', 'form_type')
