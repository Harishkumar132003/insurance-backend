"""add cost_items to pre_auth_stay

The Cost Estimates section became an editable line-item table (Expense Category /
Description / Amount) with a variable number of rows, so it can't be typed
columns. The existing scalar cost columns stay as the flat mirror that Part C/D
printing, the dashboard funnel and the approval caps read.

Revision ID: e3f7b2a91c45
Revises: d9e4b7a1c806
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e3f7b2a91c45"
down_revision = "d9e4b7a1c806"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pre_auth_stay",
        sa.Column("cost_items", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Backfill from the scalar columns so pre-existing forms open with a
    # populated table instead of an empty one. Mirrors the client-side
    # hydration, and keeps the same row order the old grid rendered in.
    # room_rent / icu_charges hold per-day rates; the rest are flat amounts.
    op.execute("""
        UPDATE pre_auth_stay SET cost_items = (
            SELECT COALESCE(jsonb_agg(row ORDER BY ord), '[]'::jsonb)
              FROM (
                SELECT 1 AS ord, jsonb_build_object(
                    'key', 'room_rent', 'label', 'Non ICU Room',
                    'description', NULL, 'amount', room_rent) AS row
                 WHERE room_rent IS NOT NULL
                UNION ALL
                SELECT 2, jsonb_build_object(
                    'key', 'icu_charges', 'label', 'ICU Charges',
                    'description', NULL, 'amount', icu_charges)
                 WHERE icu_charges IS NOT NULL
                UNION ALL
                SELECT 3, jsonb_build_object(
                    'key', 'investigation_cost', 'label', 'Investigation Cost',
                    'description', NULL, 'amount', investigation_cost)
                 WHERE investigation_cost IS NOT NULL
                UNION ALL
                SELECT 4, jsonb_build_object(
                    'key', 'ot_charges', 'label', 'OT Charges',
                    'description', NULL, 'amount', ot_charges)
                 WHERE ot_charges IS NOT NULL
                UNION ALL
                SELECT 5, jsonb_build_object(
                    'key', 'professional_fees', 'label', 'Professional Fees',
                    'description', NULL, 'amount', professional_fees)
                 WHERE professional_fees IS NOT NULL
                UNION ALL
                SELECT 6, jsonb_build_object(
                    'key', 'medicines_cost', 'label', 'Medicines Cost',
                    'description', NULL, 'amount', medicines_cost)
                 WHERE medicines_cost IS NOT NULL
                UNION ALL
                SELECT 7, jsonb_build_object(
                    'key', 'package_charges', 'label', 'Package Charges',
                    'description', NULL, 'amount', package_charges)
                 WHERE package_charges IS NOT NULL
                UNION ALL
                SELECT 8, jsonb_build_object(
                    'key', 'other_expenses', 'label', 'Other Expenses',
                    'description', NULL, 'amount', other_expenses)
                 WHERE other_expenses IS NOT NULL
              ) AS rows
        )
    """)


def downgrade() -> None:
    op.drop_column("pre_auth_stay", "cost_items")
