"""add access column to users

Revision ID: a3f8b1d6c9e2
Revises: e9a2c5b8d3f6
Create Date: 2026-04-22 00:00:00.000000

Per-user tab allow-list. NULL = full access (keeps existing users unchanged).
Empty array = no tabs. Listed keys restrict to those tabs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f8b1d6c9e2'
down_revision: Union[str, None] = 'e9a2c5b8d3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("access", sa.ARRAY(sa.String()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "access")
