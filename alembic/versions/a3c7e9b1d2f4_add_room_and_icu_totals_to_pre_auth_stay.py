"""add room_rent_total + icu_charges_total to pre_auth_stay

Adds two server-derived columns to pre_auth_stay (each = per-day rate * days):
  room_rent_total   = room_rent   (per day) * non-ICU days (max(0, expected - icu))
  icu_charges_total = icu_charges (per day) * ICU days
Backfilled for existing rows with the same formulas. The application recomputes
both on every save.

Revision ID: a3c7e9b1d2f4
Revises: f2b3c4d5e6a7
Create Date: 2026-06-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'a3c7e9b1d2f4'
down_revision = 'f2b3c4d5e6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'pre_auth_stay',
        sa.Column('room_rent_total', sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        'pre_auth_stay',
        sa.Column('icu_charges_total', sa.Numeric(12, 2), nullable=True),
    )
    # Backfill existing rows from the per-day rates and day counts.
    op.execute("""
        UPDATE pre_auth_stay
           SET room_rent_total =
                 COALESCE(room_rent, 0)
                   * GREATEST(0, COALESCE(expected_days, 0) - COALESCE(icu_days, 0)),
               icu_charges_total =
                 COALESCE(icu_charges, 0) * COALESCE(icu_days, 0)
    """)


def downgrade():
    op.drop_column('pre_auth_stay', 'icu_charges_total')
    op.drop_column('pre_auth_stay', 'room_rent_total')
