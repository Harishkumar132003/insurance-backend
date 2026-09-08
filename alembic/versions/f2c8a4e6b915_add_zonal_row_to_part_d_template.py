"""add a Zonal Disallowance row to the stored PART_D template

The Authorization Summary on the printed letter lists Discount / Co-Pay /
Deductibles but has no zonal row, so a zonal disallowance would be subtracted
from the authorised total without ever appearing on the letter the hospital
receives.

The template body lives in the DB and is fetched at runtime, so existing
databases need their stored HTML rewritten -- the seed migration only covers
fresh ones.

Non-destructive by design: the UPDATE matches on the exact Co-Pay row from the
seeded template and inserts after it, so a hand-customised template (or one
already carrying the row) is left untouched. Re-running is a no-op because the
anchor no longer matches once the zonal row is present.

Revision ID: f2c8a4e6b915
Revises: e8b4d2f9a370
Create Date: 2026-09-08
"""
from alembic import op

revision = 'f2c8a4e6b915'
down_revision = 'e8b4d2f9a370'
branch_labels = None
depends_on = None

_CO_PAY_ROW = (
    '<tr><td class="summary-label">Co-Pay</td>'
    '<td>:(INR) {{co_pay}}</td></tr>'
)
_ZONAL_ROW = (
    '<tr><td class="summary-label">Zonal Disallowance</td>'
    '<td>:(INR) {{zonal}}</td></tr>'
)


def upgrade():
    op.execute(
        f"""
        UPDATE form_templates
           SET html_content = replace(
                 html_content,
                 '{_CO_PAY_ROW}',
                 '{_CO_PAY_ROW}\n    {_ZONAL_ROW}'
               )
         WHERE form_type = 'PART_D'
           AND html_content LIKE '%{_CO_PAY_ROW}%'
           AND html_content NOT LIKE '%{{{{zonal}}}}%'
        """
    )


def downgrade():
    op.execute(
        f"""
        UPDATE form_templates
           SET html_content = replace(
                 html_content,
                 '{_CO_PAY_ROW}\n    {_ZONAL_ROW}',
                 '{_CO_PAY_ROW}'
               )
         WHERE form_type = 'PART_D'
        """
    )
