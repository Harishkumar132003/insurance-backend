"""add features table and seed default feature keys

Revision ID: b5c9e4a8f2d1
Revises: a3f8b1d6c9e2
Create Date: 2026-04-22 00:30:00.000000

Feature keys used to live as a hardcoded tuple in app/core/features.py. Move
them into a `features` table so admins can add / rename / disable tabs from
the UI.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b5c9e4a8f2d1'
down_revision: Union[str, None] = 'a3f8b1d6c9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_FEATURES = [
    ("dashboard",        "Dashboard"),
    ("preauth_list",     "PreAuth List"),
    ("query_management", "Query Management"),
    ("preauth_form",     "Pre Auth Form"),
]


def upgrade() -> None:
    conn = op.get_bind()
    # Base.metadata.create_all() in main.py may have already created this table
    # on server reload — skip the CREATE if so, but always run the seed inserts.
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS features (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key VARCHAR NOT NULL,
            label VARCHAR,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT uq_features_key UNIQUE (key)
        )
    """))

    for key, label in DEFAULT_FEATURES:
        conn.execute(
            sa.text(
                "INSERT INTO features (id, key, label) "
                "VALUES (gen_random_uuid(), :k, :l) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key, "l": label},
        )


def downgrade() -> None:
    op.drop_table("features")
