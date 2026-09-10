"""join ai-db-struct consolidation with merge-chat feature migrations

Revision ID: 246a33bec0bf
Revises: a1b2c3d4e5f7, f2c8a4e6b915
Create Date: 2026-09-08 16:28:29.981394

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '246a33bec0bf'
down_revision: Union[str, None] = ('a1b2c3d4e5f7', 'f2c8a4e6b915')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
