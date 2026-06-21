"""add preauth_status to pre_auth (mirrors case_status during pre-auth phase)

Adds pre_auth.preauth_status — the case's pre-auth workflow status mirrored onto
the PRE_AUTH-stage row from hospitalization.case_status while
current_stage='PRE_AUTH', then frozen once the claim is raised. Kept in sync by a
DB trigger so no application code has to maintain it (and it can't drift).

Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-06-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'f2b3c4d5e6a7'
down_revision = 'e1a2b3c4d5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'pre_auth',
        sa.Column('preauth_status', sa.String(), nullable=False, server_default='DRAFT'),
    )

    # Backfill: cases still in pre-auth -> live case_status; cases already in
    # claim stage -> freeze at the LAST pre-auth-stage status from status_history
    # (the true status when the pre-auth phase ended), falling back to
    # preauth_outcome, then the existing value.
    op.execute("""
        UPDATE pre_auth p SET preauth_status = h.case_status
          FROM hospitalization h
         WHERE p.claim_case_id = h.id AND p.stage = 'PRE_AUTH'
           AND h.current_stage = 'PRE_AUTH'
    """)
    op.execute("""
        UPDATE pre_auth p
           SET preauth_status = COALESCE(sh.status, h.preauth_outcome, p.preauth_status)
          FROM hospitalization h
          LEFT JOIN LATERAL (
                SELECT s.status
                  FROM status_history s
                 WHERE s.claim_case_id = h.id AND s.stage = 'PRE_AUTH'
                 ORDER BY s.created_at DESC
                 LIMIT 1
          ) sh ON true
         WHERE p.claim_case_id = h.id AND p.stage = 'PRE_AUTH'
           AND h.current_stage = 'CLAIM'
    """)

    # CLAIM-stage rows inherit the case's (frozen) pre-auth status from its
    # PRE_AUTH row, so they don't show the misleading default 'DRAFT'.
    op.execute("""
        UPDATE pre_auth c SET preauth_status = pa.preauth_status
          FROM pre_auth pa
         WHERE pa.claim_case_id = c.claim_case_id AND pa.stage = 'PRE_AUTH'
           AND c.stage = 'CLAIM'
    """)

    # Sync trigger: mirror case_status onto the PRE_AUTH row, only while the case
    # is still in the pre-auth phase. Once current_stage flips to CLAIM the WHEN
    # clause is false, so the value freezes automatically.
    op.execute("""
        CREATE OR REPLACE FUNCTION public.sync_preauth_status() RETURNS trigger
        LANGUAGE plpgsql AS $func$
        BEGIN
            UPDATE public.pre_auth
               SET preauth_status = NEW.case_status
             WHERE claim_case_id = NEW.id AND stage = 'PRE_AUTH';
            RETURN NEW;
        END;
        $func$;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_sync_preauth_status ON public.hospitalization;")
    op.execute("""
        CREATE TRIGGER trg_sync_preauth_status
        AFTER UPDATE OF case_status ON public.hospitalization
        FOR EACH ROW
        WHEN (NEW.current_stage = 'PRE_AUTH')
        EXECUTE FUNCTION public.sync_preauth_status();
    """)

    # When a CLAIM-stage pre_auth row is created, inherit the case's pre-auth
    # status from its PRE_AUTH row (the sync trigger above no longer fires once
    # the case is in claim stage). Guarded so a missing PRE_AUTH row can't NULL it.
    op.execute("""
        CREATE OR REPLACE FUNCTION public.inherit_preauth_status() RETURNS trigger
        LANGUAGE plpgsql AS $func$
        DECLARE v varchar;
        BEGIN
            SELECT pa.preauth_status INTO v
              FROM public.pre_auth pa
             WHERE pa.claim_case_id = NEW.claim_case_id AND pa.stage = 'PRE_AUTH'
             ORDER BY pa.id LIMIT 1;
            IF v IS NOT NULL THEN
                NEW.preauth_status := v;
            END IF;
            RETURN NEW;
        END;
        $func$;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_inherit_preauth_status ON public.pre_auth;")
    op.execute("""
        CREATE TRIGGER trg_inherit_preauth_status
        BEFORE INSERT ON public.pre_auth
        FOR EACH ROW
        WHEN (NEW.stage = 'CLAIM')
        EXECUTE FUNCTION public.inherit_preauth_status();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_inherit_preauth_status ON public.pre_auth;")
    op.execute("DROP FUNCTION IF EXISTS public.inherit_preauth_status();")
    op.execute("DROP TRIGGER IF EXISTS trg_sync_preauth_status ON public.hospitalization;")
    op.execute("DROP FUNCTION IF EXISTS public.sync_preauth_status();")
    op.drop_column('pre_auth', 'preauth_status')
