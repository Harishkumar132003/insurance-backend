"""add tpa fields to policy_provider_configs

Revision ID: b3a7f1c2d4e8
Revises: e91243b4df9a
Create Date: 2026-04-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3a7f1c2d4e8'
down_revision: Union[str, None] = 'e91243b4df9a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('policy_provider_configs', sa.Column('tpa_name', sa.String(), nullable=True))
    op.add_column('policy_provider_configs', sa.Column('tpa_toll_free_phone', sa.String(), nullable=True))
    op.add_column('policy_provider_configs', sa.Column('tpa_toll_free_fax', sa.String(), nullable=True))

    # Update existing rows with random values
    op.execute("""
        UPDATE policy_provider_configs
        SET tpa_name = 'TPA-' || substr(md5(random()::text), 1, 8),
            tpa_toll_free_phone = '1-800-' || lpad((random() * 9999999)::int::text, 7, '0'),
            tpa_toll_free_fax = '1-800-' || lpad((random() * 9999999)::int::text, 7, '0')
    """)


def downgrade() -> None:
    op.drop_column('policy_provider_configs', 'tpa_toll_free_fax')
    op.drop_column('policy_provider_configs', 'tpa_toll_free_phone')
    op.drop_column('policy_provider_configs', 'tpa_name')
