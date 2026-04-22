"""add app_password to hospitals

Revision ID: c6b4e7f2a9d3
Revises: b5c9e4a8f2d1
Create Date: 2026-04-22 01:00:00.000000

Stores the encrypted (Fernet) email app password per hospital. Key derivation
uses HOSPITAL_SECRETS_KEY + rohini_id via HKDF, so the ciphertext is unusable
without the env-side master key even if the DB is compromised.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c6b4e7f2a9d3'
down_revision: Union[str, None] = 'b5c9e4a8f2d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hospitals",
        sa.Column("app_password", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hospitals", "app_password")
