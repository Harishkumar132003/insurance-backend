"""replace schema_json with html_content in form_templates

Revision ID: a8c3e6f1d2b4
Revises: d5e9f2a1b7c3
Create Date: 2026-04-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8c3e6f1d2b4'
down_revision: Union[str, None] = 'd5e9f2a1b7c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('form_templates', sa.Column('html_content', sa.Text(), nullable=True))

    # Backfill existing rows with mock HTML content
    op.execute("""
        UPDATE form_templates
        SET html_content = '<h1>Sample Form</h1><p>This is a mock form template.</p>'
    """)

    op.drop_column('form_templates', 'schema_json')


def downgrade() -> None:
    op.add_column('form_templates', sa.Column('schema_json', sa.JSON(), nullable=True))
    op.execute("""
        UPDATE form_templates
        SET schema_json = '{"sections": []}'::jsonb
    """)
    op.alter_column('form_templates', 'schema_json', nullable=False)
    op.drop_column('form_templates', 'html_content')
