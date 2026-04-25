"""add policy_provider_id to users

Revision ID: 26807d186f87
Revises: 8e5a6e490fe8
Create Date: 2026-04-24 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '26807d186f87'
down_revision: Union[str, None] = '8e5a6e490fe8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('policy_provider_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_users_policy_provider_id_policy_provider_configs',
        'users',
        'policy_provider_configs',
        ['policy_provider_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_users_policy_provider_id_policy_provider_configs',
        'users',
        type_='foreignkey',
    )
    op.drop_column('users', 'policy_provider_id')
