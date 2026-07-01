"""add preauth_status_tracking table (AI-chat pre-auth status log)

One row per PRE_AUTH status transition (first tracked: DRAFT -> SUBMITTED; the
bare initial DRAFT is not logged). Filled by an AFTER INSERT trigger on
status_history and backfilled from existing history. One case -> many rows.

Revision ID: b1d4f7a2c9e3
Revises: a9c2e5f7b1d4
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'b1d4f7a2c9e3'
down_revision = 'a9c2e5f7b1d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'preauth_status_tracking',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('hospitalization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('hospitalization.id'), nullable=False),
        sa.Column('uhid', sa.String(), nullable=True),
        sa.Column('from_status', sa.String(), nullable=True),
        sa.Column('to_status', sa.String(), nullable=False),
        sa.Column('turn_around_time', sa.Interval(), nullable=True),
        sa.Column('document_link', postgresql.JSONB(), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_preauth_status_tracking_hospitalization_id',
                    'preauth_status_tracking', ['hospitalization_id'])

    # Trigger: log every PRE_AUTH status change. The bare initial DRAFT is
    # skipped, so the first logged row is DRAFT -> SUBMITTED (TAT = time the form
    # sat in draft). document_link = JSON array of the status email's attachments.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.track_preauth_status() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    DECLARE
        prev_status varchar;
        prev_time   timestamptz;
        v_uhid      varchar;
        v_docs      jsonb;
    BEGIN
        IF NEW.stage <> 'PRE_AUTH' THEN RETURN NEW; END IF;
        IF NEW.status = 'DRAFT' THEN RETURN NEW; END IF;  -- don't log the bare draft
        SELECT sh.status, sh.created_at INTO prev_status, prev_time
          FROM public.status_history sh
         WHERE sh.claim_case_id = NEW.claim_case_id AND sh.stage = 'PRE_AUTH' AND sh.id <> NEW.id
         ORDER BY sh.created_at DESC, sh.id DESC
         LIMIT 1;
        SELECT uhid INTO v_uhid FROM public.hospitalization WHERE id = NEW.claim_case_id;
        SELECT jsonb_agg(a.file_path ORDER BY a.id) INTO v_docs
          FROM public.claim_case_email_attachments a WHERE a.email_id = NEW.email_id;
        INSERT INTO public.preauth_status_tracking
            (hospitalization_id, uhid, from_status, to_status, turn_around_time,
             document_link, remark, created_at)
        VALUES
            (NEW.claim_case_id, v_uhid, prev_status, NEW.status,
             CASE WHEN prev_time IS NOT NULL THEN NEW.created_at - prev_time ELSE NULL END,
             v_docs, NEW.remarks, NEW.created_at);
        RETURN NEW;
    END;
    $func$;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_track_preauth_status ON public.status_history;")
    op.execute("""
        CREATE TRIGGER trg_track_preauth_status
        AFTER INSERT ON public.status_history
        FOR EACH ROW EXECUTE FUNCTION public.track_preauth_status();
    """)

    # Backfill existing PRE_AUTH history (exclude the bare DRAFT rows; the DRAFT
    # row is still used as the from_status of the SUBMITTED row via LAG).
    op.execute("""
        INSERT INTO public.preauth_status_tracking
            (hospitalization_id, uhid, from_status, to_status, turn_around_time,
             document_link, remark, created_at)
        SELECT t.claim_case_id, t.uhid, t.from_status, t.to_status, t.tat,
               t.docs, t.remarks, t.created_at
        FROM (
            SELECT sh.claim_case_id,
                   h.uhid,
                   LAG(sh.status)     OVER w AS from_status,
                   sh.status          AS to_status,
                   sh.created_at - LAG(sh.created_at) OVER w AS tat,
                   (SELECT jsonb_agg(a.file_path ORDER BY a.id)
                      FROM public.claim_case_email_attachments a
                     WHERE a.email_id = sh.email_id) AS docs,
                   sh.remarks,
                   sh.created_at
            FROM public.status_history sh
            JOIN public.hospitalization h ON h.id = sh.claim_case_id
            WHERE sh.stage = 'PRE_AUTH'
            WINDOW w AS (PARTITION BY sh.claim_case_id ORDER BY sh.created_at, sh.id)
        ) t
        WHERE t.to_status <> 'DRAFT'
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_track_preauth_status ON public.status_history;")
    op.execute("DROP FUNCTION IF EXISTS public.track_preauth_status();")
    op.drop_index('ix_preauth_status_tracking_hospitalization_id', table_name='preauth_status_tracking')
    op.drop_table('preauth_status_tracking')
