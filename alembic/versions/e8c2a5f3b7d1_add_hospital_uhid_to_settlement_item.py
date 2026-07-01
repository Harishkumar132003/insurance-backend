"""add hospital_id + uhid to settlement_item

Denormalised convenience columns kept in sync by a BEFORE INSERT/UPDATE trigger:
  hospital_id = the batch's hospital (settlement_batch.hospital_id) — always set.
  uhid        = the matched case's UHID (via claim_case_id) — NULL when unmatched.
The trigger fires on insert and whenever batch_id / claim_case_id changes (e.g.
when a line is later matched to a case), so it works for future rows too.

Revision ID: e8c2a5f3b7d1
Revises: d7b3f1c9a2e4
Create Date: 2026-07-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'e8c2a5f3b7d1'
down_revision = 'd7b3f1c9a2e4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('settlement_item',
                  sa.Column('hospital_id', postgresql.UUID(as_uuid=True),
                            sa.ForeignKey('hospitals.id'), nullable=True))
    op.add_column('settlement_item', sa.Column('uhid', sa.String(), nullable=True))
    op.create_index('ix_settlement_item_hospital_id', 'settlement_item', ['hospital_id'])

    op.execute("""
    CREATE OR REPLACE FUNCTION public.fill_settlement_item_denorm() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    BEGIN
        SELECT b.hospital_id INTO NEW.hospital_id
          FROM public.settlement_batch b WHERE b.id = NEW.batch_id;
        IF NEW.claim_case_id IS NOT NULL THEN
            SELECT h.uhid INTO NEW.uhid
              FROM public.hospitalization h WHERE h.id = NEW.claim_case_id;
        ELSE
            NEW.uhid := NULL;
        END IF;
        RETURN NEW;
    END;
    $func$;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_fill_settlement_item_denorm ON public.settlement_item;")
    op.execute("""
        CREATE TRIGGER trg_fill_settlement_item_denorm
        BEFORE INSERT OR UPDATE OF batch_id, claim_case_id ON public.settlement_item
        FOR EACH ROW EXECUTE FUNCTION public.fill_settlement_item_denorm();
    """)

    # Backfill existing rows.
    op.execute("""
        UPDATE public.settlement_item si SET
            hospital_id = (SELECT hospital_id FROM public.settlement_batch WHERE id = si.batch_id),
            uhid = (SELECT uhid FROM public.hospitalization WHERE id = si.claim_case_id)
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_fill_settlement_item_denorm ON public.settlement_item;")
    op.execute("DROP FUNCTION IF EXISTS public.fill_settlement_item_denorm();")
    op.drop_index('ix_settlement_item_hospital_id', table_name='settlement_item')
    op.drop_column('settlement_item', 'uhid')
    op.drop_column('settlement_item', 'hospital_id')
