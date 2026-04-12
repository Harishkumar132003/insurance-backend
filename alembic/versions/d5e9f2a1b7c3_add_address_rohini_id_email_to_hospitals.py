"""add address, rohini_id, email to hospitals

Revision ID: d5e9f2a1b7c3
Revises: b3a7f1c2d4e8
Create Date: 2026-04-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e9f2a1b7c3'
down_revision: Union[str, None] = 'b3a7f1c2d4e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hospitals', sa.Column('address', sa.String(), nullable=True))
    op.add_column('hospitals', sa.Column('rohini_id', sa.String(), nullable=True))
    op.add_column('hospitals', sa.Column('email', sa.String(), nullable=True))

    # Update existing rows with random values
    op.execute("""
        UPDATE hospitals
        SET address = 'Address-' || substr(md5(random()::text), 1, 8),
            rohini_id = 'ROH-' || lpad((random() * 999999)::int::text, 6, '0'),
            email = 'hospital-' || substr(md5(random()::text), 1, 6) || '@example.com'
    """)


def downgrade() -> None:
    op.drop_column('hospitals', 'email')
    op.drop_column('hospitals', 'rohini_id')
    op.drop_column('hospitals', 'address')
