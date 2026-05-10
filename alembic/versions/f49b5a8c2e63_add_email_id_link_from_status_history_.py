"""add email_id link from status_history to claim_case_emails

Revision ID: f49b5a8c2e63
Revises: e7a2d9c4f150
Create Date: 2026-05-08 15:38:34.947086

Lets the claim-case timeline UI open the email + attachments tied to a
specific status change in one click. Nullable — old rows stay NULL,
DRAFT / manual status updates also stay NULL (no email exists for them).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f49b5a8c2e63'
down_revision: Union[str, None] = 'e7a2d9c4f150'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'status_history',
        sa.Column('email_id', sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        'fk_status_history_email_id',
        'status_history', 'claim_case_emails',
        ['email_id'], ['id'],
    )
    op.create_index(
        'ix_status_history_email_id',
        'status_history',
        ['email_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_status_history_email_id', table_name='status_history')
    op.drop_constraint('fk_status_history_email_id', 'status_history', type_='foreignkey')
    op.drop_column('status_history', 'email_id')
