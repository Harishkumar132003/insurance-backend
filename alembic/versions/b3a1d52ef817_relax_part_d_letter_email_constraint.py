"""relax part_d_letter email constraint to allow drafts

Revision ID: b3a1d52ef817
Revises: a7c81b3e9f02
Create Date: 2026-05-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3a1d52ef817'
down_revision: Union[str, None] = 'a7c81b3e9f02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Allow a Part-D draft to exist before any approval email is created.
    op.alter_column(
        'part_d_letters', 'claim_case_email_id',
        existing_type=sa.BigInteger(),
        nullable=True,
    )

    # Replace the single-column unique with two partial unique indexes so the
    # "one per approval email" invariant stays, and drafts get their own
    # "one per claim_case" invariant.
    op.drop_constraint('uq_part_d_letter_email', 'part_d_letters', type_='unique')
    op.create_index(
        'uq_part_d_letter_email',
        'part_d_letters',
        ['claim_case_email_id'],
        unique=True,
        postgresql_where=sa.text('claim_case_email_id IS NOT NULL'),
    )
    op.create_index(
        'uq_part_d_letter_draft',
        'part_d_letters',
        ['claim_case_id'],
        unique=True,
        postgresql_where=sa.text('claim_case_email_id IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_part_d_letter_draft', table_name='part_d_letters')
    op.drop_index('uq_part_d_letter_email', table_name='part_d_letters')
    op.create_unique_constraint(
        'uq_part_d_letter_email', 'part_d_letters', ['claim_case_email_id'],
    )
    op.alter_column(
        'part_d_letters', 'claim_case_email_id',
        existing_type=sa.BigInteger(),
        nullable=False,
    )
