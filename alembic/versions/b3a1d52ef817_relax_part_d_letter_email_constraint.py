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
    # Idempotent: this migration can land on a server whose schema was
    # already brought up to date out-of-band (e.g. via Base.metadata.create_all),
    # so the constraint/columns it manipulates may already be in their final
    # shape. Inspect first, then only emit DDL for what's still mismatched.
    bind = op.get_bind()
    insp = sa.inspect(bind)

    cols = {c['name']: c for c in insp.get_columns('part_d_letters')}
    if cols.get('claim_case_email_id', {}).get('nullable') is False:
        # Allow a Part-D draft to exist before any approval email is created.
        op.alter_column(
            'part_d_letters', 'claim_case_email_id',
            existing_type=sa.BigInteger(),
            nullable=True,
        )

    # Replace the single-column unique with two partial unique indexes so the
    # "one per approval email" invariant stays, and drafts get their own
    # "one per claim_case" invariant.
    unique_constraints = {u['name'] for u in insp.get_unique_constraints('part_d_letters')}
    if 'uq_part_d_letter_email' in unique_constraints:
        op.drop_constraint('uq_part_d_letter_email', 'part_d_letters', type_='unique')

    existing_indexes = {i['name'] for i in insp.get_indexes('part_d_letters')}
    if 'uq_part_d_letter_email' not in existing_indexes:
        op.create_index(
            'uq_part_d_letter_email',
            'part_d_letters',
            ['claim_case_email_id'],
            unique=True,
            postgresql_where=sa.text('claim_case_email_id IS NOT NULL'),
        )
    if 'uq_part_d_letter_draft' not in existing_indexes:
        op.create_index(
            'uq_part_d_letter_draft',
            'part_d_letters',
            ['claim_case_id'],
            unique=True,
            postgresql_where=sa.text('claim_case_email_id IS NULL'),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_indexes = {i['name'] for i in insp.get_indexes('part_d_letters')}
    if 'uq_part_d_letter_draft' in existing_indexes:
        op.drop_index('uq_part_d_letter_draft', table_name='part_d_letters')
    if 'uq_part_d_letter_email' in existing_indexes:
        op.drop_index('uq_part_d_letter_email', table_name='part_d_letters')

    unique_constraints = {u['name'] for u in insp.get_unique_constraints('part_d_letters')}
    if 'uq_part_d_letter_email' not in unique_constraints:
        op.create_unique_constraint(
            'uq_part_d_letter_email', 'part_d_letters', ['claim_case_email_id'],
        )

    cols = {c['name']: c for c in insp.get_columns('part_d_letters')}
    if cols.get('claim_case_email_id', {}).get('nullable') is True:
        op.alter_column(
            'part_d_letters', 'claim_case_email_id',
            existing_type=sa.BigInteger(),
            nullable=False,
        )
