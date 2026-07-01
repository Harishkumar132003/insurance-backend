"""make pre_auth always PRE_AUTH (drop stage; move claim bill items to the case)

- Fix the pre_auth mirror triggers broken by the earlier claim_case_id ->
  hospitalization_id rename (they still referenced claim_case_id + stage).
- Drop the obsolete inherit_preauth_status trigger (claim-stage pre_auth rows
  are going away).
- Re-anchor claim_bill_item from pre_auth (form_data_id) to the case
  (hospitalization_id); backfill from the CLAIM pre_auth rows.
- Delete the CLAIM-stage pre_auth rows, then drop pre_auth.stage.

Revision ID: b9e2d5f8a3c1
Revises: a1c4e7b2d9f6
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'b9e2d5f8a3c1'
down_revision = 'a1c4e7b2d9f6'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Fix the case-status / approved-amount mirror triggers (use the renamed
    #    hospitalization_id column; pre_auth is now PRE_AUTH-only, so no stage).
    op.execute("""
        CREATE OR REPLACE FUNCTION public.sync_preauth_status() RETURNS trigger
        LANGUAGE plpgsql AS $func$
        BEGIN
            UPDATE public.pre_auth SET preauth_status = NEW.case_status
             WHERE hospitalization_id = NEW.id;
            RETURN NEW;
        END;
        $func$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.sync_preauth_approved_amount() RETURNS trigger
        LANGUAGE plpgsql AS $func$
        BEGIN
            UPDATE public.pre_auth SET preauth_approved_amount = NEW.approved_amount
             WHERE hospitalization_id = NEW.id;
            RETURN NEW;
        END;
        $func$;
    """)

    # 2. Drop the obsolete inherit trigger (referenced pre_auth.stage='CLAIM').
    op.execute("DROP TRIGGER IF EXISTS trg_inherit_preauth_status ON public.pre_auth;")
    op.execute("DROP FUNCTION IF EXISTS public.inherit_preauth_status();")

    # 3. Re-anchor claim_bill_item on the case.
    op.add_column('claim_bill_item',
                  sa.Column('hospitalization_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.execute("""
        UPDATE claim_bill_item cbi
           SET hospitalization_id = pa.hospitalization_id
          FROM pre_auth pa
         WHERE pa.id = cbi.form_data_id
    """)
    op.execute("DELETE FROM claim_bill_item WHERE hospitalization_id IS NULL")
    # The read-only RLS policy scopes via form_data_id; drop it before dropping
    # the column, then recreate it scoped via the new case anchor.
    op.execute("DROP POLICY IF EXISTS ai_ro_tenant ON public.claim_bill_item;")
    # Dropping form_data_id removes its FK (cascade) + index, so the CLAIM
    # pre_auth deletes below won't cascade-delete the (re-anchored) bill items.
    op.drop_column('claim_bill_item', 'form_data_id')
    op.alter_column('claim_bill_item', 'hospitalization_id', nullable=False)
    op.create_foreign_key(
        'fk_claim_bill_item_hospitalization', 'claim_bill_item',
        'hospitalization', ['hospitalization_id'], ['id'], ondelete='CASCADE')
    op.create_index('ix_claim_bill_item_hospitalization_id',
                    'claim_bill_item', ['hospitalization_id'])
    op.execute("""
        CREATE POLICY ai_ro_tenant ON public.claim_bill_item
            FOR SELECT TO oasys_ai_ro
            USING (hospitalization_id IN (
                SELECT id FROM public.hospitalization
                 WHERE hospital_id = oasys_current_hospital()));
    """)

    # 4. Remove CLAIM-stage pre_auth rows, then drop the stage column.
    op.execute("DELETE FROM pre_auth WHERE stage = 'CLAIM'")
    op.drop_column('pre_auth', 'stage')


def downgrade():
    # Schema-only restore (lossy: deleted CLAIM rows / original bill-item anchor
    # are not recoverable).
    op.add_column('pre_auth',
                  sa.Column('stage', sa.String(), nullable=False, server_default='PRE_AUTH'))
    op.execute("DROP POLICY IF EXISTS ai_ro_tenant ON public.claim_bill_item;")
    op.drop_index('ix_claim_bill_item_hospitalization_id', table_name='claim_bill_item')
    op.drop_constraint('fk_claim_bill_item_hospitalization', 'claim_bill_item', type_='foreignkey')
    op.add_column('claim_bill_item', sa.Column('form_data_id', sa.BigInteger(), nullable=True))
    op.create_index('ix_claim_bill_item_form_data_id', 'claim_bill_item', ['form_data_id'])
    op.drop_column('claim_bill_item', 'hospitalization_id')
    op.execute("""
        CREATE POLICY ai_ro_tenant ON public.claim_bill_item
            FOR SELECT TO oasys_ai_ro
            USING (form_data_id IN (
                SELECT pa.id FROM pre_auth pa
                  JOIN hospitalization h ON h.id = pa.hospitalization_id
                 WHERE h.hospital_id = oasys_current_hospital()));
    """)
