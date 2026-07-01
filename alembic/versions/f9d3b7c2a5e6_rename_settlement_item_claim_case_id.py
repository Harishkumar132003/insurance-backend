"""rename settlement_item.claim_case_id -> hospitalization_id

Renames the FK column (+ its constraint and index) and updates the
fill_settlement_item_denorm trigger to reference the new column. ORM keeps the
attribute claim_case_id (code unchanged). The RLS policy scopes via batch_id, so
it's unaffected.

Revision ID: f9d3b7c2a5e6
Revises: e8c2a5f3b7d1
Create Date: 2026-07-01
"""
from alembic import op

revision = 'f9d3b7c2a5e6'
down_revision = 'e8c2a5f3b7d1'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('settlement_item', 'claim_case_id', new_column_name='hospitalization_id')
    op.execute("ALTER TABLE settlement_item RENAME CONSTRAINT settlement_item_claim_case_id_fkey "
               "TO settlement_item_hospitalization_id_fkey")
    op.execute("ALTER INDEX IF EXISTS ix_settlement_item_claim_case_id "
               "RENAME TO ix_settlement_item_hospitalization_id")

    # Update the denorm trigger to read the renamed column.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.fill_settlement_item_denorm() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    BEGIN
        SELECT b.hospital_id INTO NEW.hospital_id
          FROM public.settlement_batch b WHERE b.id = NEW.batch_id;
        IF NEW.hospitalization_id IS NOT NULL THEN
            SELECT h.uhid INTO NEW.uhid
              FROM public.hospitalization h WHERE h.id = NEW.hospitalization_id;
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
        BEFORE INSERT OR UPDATE OF batch_id, hospitalization_id ON public.settlement_item
        FOR EACH ROW EXECUTE FUNCTION public.fill_settlement_item_denorm();
    """)


def downgrade():
    op.execute("ALTER INDEX IF EXISTS ix_settlement_item_hospitalization_id "
               "RENAME TO ix_settlement_item_claim_case_id")
    op.execute("ALTER TABLE settlement_item RENAME CONSTRAINT settlement_item_hospitalization_id_fkey "
               "TO settlement_item_claim_case_id_fkey")
    op.alter_column('settlement_item', 'hospitalization_id', new_column_name='claim_case_id')
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
