"""add bd_items to part_d_letters

The Review & Approve bill breakdown became one row per hospital line item, so it
can no longer be a fixed set of bd_* columns — two named investigations must stay
two rows. The bd_* scalars remain as the flat mirror the letter template and
buildFlatArgs() read.

Revision ID: f4a8c1e7b309
Revises: e3f7b2a91c45
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f4a8c1e7b309"
down_revision = "e3f7b2a91c45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "part_d_letters",
        sa.Column("bd_items", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Backfill from the scalar columns so a letter saved before this change
    # reopens with a populated breakdown instead of an empty one. Mirrors the
    # client-side synthesis. `claimed` equals `amount` here because the split
    # against the hospital's original ask wasn't recorded on these rows.
    op.execute("""
        UPDATE part_d_letters SET bd_items = (
            SELECT COALESCE(jsonb_agg(row ORDER BY ord), '[]'::jsonb)
              FROM (
                SELECT 1 AS ord, jsonb_build_object(
                    'key','room_rent','label','Non ICU Room','description',NULL,
                    'claimed', bd_room_rent, 'amount', bd_room_rent) AS row
                 WHERE bd_room_rent IS NOT NULL
                UNION ALL SELECT 2, jsonb_build_object(
                    'key','icu_charges','label','ICU Charges','description',NULL,
                    'claimed', bd_icu_charges, 'amount', bd_icu_charges)
                 WHERE bd_icu_charges IS NOT NULL
                UNION ALL SELECT 3, jsonb_build_object(
                    'key','investigation_cost','label','Investigation Cost','description',NULL,
                    'claimed', bd_investigation_cost, 'amount', bd_investigation_cost)
                 WHERE bd_investigation_cost IS NOT NULL
                UNION ALL SELECT 4, jsonb_build_object(
                    'key','ot_charges','label','OT Charges','description',NULL,
                    'claimed', bd_ot_charges, 'amount', bd_ot_charges)
                 WHERE bd_ot_charges IS NOT NULL
                UNION ALL SELECT 5, jsonb_build_object(
                    'key','professional_fees','label','Professional Fees','description',NULL,
                    'claimed', bd_professional_fees, 'amount', bd_professional_fees)
                 WHERE bd_professional_fees IS NOT NULL
                UNION ALL SELECT 6, jsonb_build_object(
                    'key','medicines_cost','label','Medicines Cost','description',NULL,
                    'claimed', bd_medicines_cost, 'amount', bd_medicines_cost)
                 WHERE bd_medicines_cost IS NOT NULL
                UNION ALL SELECT 7, jsonb_build_object(
                    'key','package_charges','label','Package Charges','description',NULL,
                    'claimed', bd_package_charges, 'amount', bd_package_charges)
                 WHERE bd_package_charges IS NOT NULL
                UNION ALL SELECT 8, jsonb_build_object(
                    'key','other_expenses','label','Other Expenses','description',NULL,
                    'claimed', bd_other_expenses, 'amount', bd_other_expenses)
                 WHERE bd_other_expenses IS NOT NULL
              ) AS rows
        )
    """)


def downgrade() -> None:
    op.drop_column("part_d_letters", "bd_items")
