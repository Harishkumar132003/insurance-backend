"""add ai_chat and ai_chat_message

Per-user AI assistant conversations. `ai_chat` is one conversation (owned by a
user, scoped to a hospital); `ai_chat_message` holds its messages, with the
assistant's SQL/columns/rows kept for re-rendering.

Revision ID: d2b5f9c33e07
Revises: c1a4e8f20d51
Create Date: 2026-06-11 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = 'd2b5f9c33e07'
down_revision: Union[str, None] = 'c1a4e8f20d51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_chat',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('hospital_id', UUID(as_uuid=True), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('title', sa.String(), nullable=False, server_default='New chat'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ai_chat_user_id', 'ai_chat', ['user_id'])

    op.create_table(
        'ai_chat_message',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('chat_id', UUID(as_uuid=True),
                  sa.ForeignKey('ai_chat.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('sql', JSONB(), nullable=True),
        sa.Column('columns', JSONB(), nullable=True),
        sa.Column('rows', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ai_chat_message_chat_id', 'ai_chat_message', ['chat_id'])


def downgrade() -> None:
    op.drop_index('ix_ai_chat_message_chat_id', table_name='ai_chat_message')
    op.drop_table('ai_chat_message')
    op.drop_index('ix_ai_chat_user_id', table_name='ai_chat')
    op.drop_table('ai_chat')
