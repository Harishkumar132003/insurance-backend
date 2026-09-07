"""add preauth_raised_amount + preauth_approved_amount to pre_auth

Convenience mirror columns so both pre-auth amounts read off one pre_auth row:
  preauth_raised_amount   = original pre-auth requested amount (pre_auth_stay.total_cost)
                            — set by the app in apply_sections on form save.
  preauth_approved_amount = pre-auth approved amount (hospitalization.approved_amount)
                            — kept in sync by a DB trigger on hospitalization.

Backfills both from the existing source-of-truth columns.

Revision ID: d6f0b3c7e4a9
Revises: c5e9a2b6d3f8
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op

revision = 'd6f0b3c7e4a9'
down_revision = 'c5e9a2b6d3f8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('pre_auth', sa.Column('preauth_raised_amount', sa.Numeric(12, 2), nullable=True))
    op.add_column('pre_auth', sa.Column('preauth_approved_amount', sa.Numeric(12, 2), nullable=True))

    # Backfill raised ← pre_auth_stay.total_cost (the original cost estimate).
    op.execute("""
        UPDATE pre_auth p
           SET preauth_raised_amount = s.total_cost
          FROM pre_auth_stay s
         WHERE s.form_data_id = p.id
    """)
    # Backfill approved ← hospitalization.approved_amount onto the PRE_AUTH form row.
    op.execute("""
        UPDATE pre_auth p
           SET preauth_approved_amount = h.approved_amount
          FROM hospitalization h
         WHERE h.id = p.claim_case_id AND p.stage = 'PRE_AUTH'
    """)

    # Keep preauth_approved_amount in sync whenever the case's approved amount
    # changes (mirrors the existing preauth_status trigger pattern, so every
    # approval code path is covered without touching app code).
    op.execute("""
        CREATE OR REPLACE FUNCTION public.sync_preauth_approved_amount() RETURNS trigger
        LANGUAGE plpgsql AS $func$
        BEGIN
            UPDATE public.pre_auth
               SET preauth_approved_amount = NEW.approved_amount
             WHERE claim_case_id = NEW.id AND stage = 'PRE_AUTH';
            RETURN NEW;
        END;
        $func$;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_sync_preauth_approved_amount ON public.hospitalization;")
    op.execute("""
        CREATE TRIGGER trg_sync_preauth_approved_amount
        AFTER UPDATE OF approved_amount ON public.hospitalization
        FOR EACH ROW
        EXECUTE FUNCTION public.sync_preauth_approved_amount();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_sync_preauth_approved_amount ON public.hospitalization;")
    op.execute("DROP FUNCTION IF EXISTS public.sync_preauth_approved_amount();")
    op.drop_column('pre_auth', 'preauth_approved_amount')
    op.drop_column('pre_auth', 'preauth_raised_amount')
