"""add claim_status_tracking table (AI-chat claim status log)

Sibling of preauth_status_tracking, for the CLAIM stage. One row per CLAIM status
transition (first row CLAIM_SUBMITTED, from_status NULL). Filled by a deferred
AFTER INSERT trigger on status_history (stage='CLAIM') and backfilled. Reuses the
format_tat() helper and the deduped attachments+documents logic. `remark` carries
the claim remark.

Revision ID: f3b7d2a9c5e8
Revises: e2a6c9b4f1d7
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'f3b7d2a9c5e8'
down_revision = 'e2a6c9b4f1d7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'claim_status_tracking',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('hospitalization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('hospitalization.id'), nullable=False),
        sa.Column('uhid', sa.String(), nullable=True),
        sa.Column('claim_number', sa.String(), nullable=True),
        sa.Column('email_id', sa.BigInteger(), sa.ForeignKey('claim_case_emails.id'), nullable=True),
        sa.Column('from_status', sa.String(), nullable=True),
        sa.Column('to_status', sa.String(), nullable=False),
        sa.Column('turn_around_time', sa.Interval(), nullable=True),
        sa.Column('turn_around_time_text', sa.String(), nullable=True),
        sa.Column('document_link', postgresql.JSONB(), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_claim_status_tracking_hospitalization_id',
                    'claim_status_tracking', ['hospitalization_id'])

    op.execute("""
    CREATE OR REPLACE FUNCTION public.track_claim_status() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    DECLARE
        prev_status varchar;
        prev_time   timestamptz;
        v_uhid      varchar;
        v_claimno   varchar;
        v_docs      jsonb;
        v_tat       interval;
    BEGIN
        IF NEW.stage <> 'CLAIM' THEN RETURN NEW; END IF;
        SELECT sh.status, sh.created_at INTO prev_status, prev_time
          FROM public.status_history sh
         WHERE sh.claim_case_id = NEW.claim_case_id AND sh.stage = 'CLAIM' AND sh.id <> NEW.id
         ORDER BY sh.created_at DESC, sh.id DESC
         LIMIT 1;
        SELECT uhid, claim_number INTO v_uhid, v_claimno
          FROM public.hospitalization WHERE id = NEW.claim_case_id;
        SELECT jsonb_agg(fp ORDER BY fp) INTO v_docs FROM (
            SELECT DISTINCT ON (original_filename) file_path AS fp
            FROM (
                SELECT a.original_filename, a.file_path, 1 AS pref
                  FROM public.claim_case_email_attachments a WHERE a.email_id = NEW.email_id
                UNION ALL
                SELECT d.original_filename, d.file_path, 2 AS pref
                  FROM public.claim_case_documents d WHERE d.sent_email_id = NEW.email_id
            ) u
            ORDER BY original_filename, pref
        ) y;
        v_tat := CASE WHEN prev_time IS NOT NULL THEN NEW.created_at - prev_time ELSE NULL END;
        INSERT INTO public.claim_status_tracking
            (hospitalization_id, uhid, claim_number, email_id, from_status, to_status,
             turn_around_time, turn_around_time_text, document_link, remark, created_at)
        VALUES
            (NEW.claim_case_id, v_uhid, v_claimno, NEW.email_id, prev_status, NEW.status,
             v_tat, public.format_tat(v_tat), v_docs, NEW.remarks, NEW.created_at);
        RETURN NEW;
    END;
    $func$;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_track_claim_status ON public.status_history;")
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_track_claim_status
        AFTER INSERT ON public.status_history
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION public.track_claim_status();
    """)

    # Backfill existing CLAIM-stage history.
    op.execute("""
        INSERT INTO public.claim_status_tracking
            (hospitalization_id, uhid, claim_number, email_id, from_status, to_status,
             turn_around_time, turn_around_time_text, document_link, remark, created_at)
        SELECT t.claim_case_id, t.uhid, t.claim_number, t.email_id, t.from_status, t.to_status,
               t.tat, public.format_tat(t.tat), t.docs, t.remarks, t.created_at
        FROM (
            SELECT sh.claim_case_id,
                   h.uhid, h.claim_number,
                   sh.email_id,
                   LAG(sh.status)     OVER w AS from_status,
                   sh.status          AS to_status,
                   sh.created_at - LAG(sh.created_at) OVER w AS tat,
                   (SELECT jsonb_agg(fp ORDER BY fp) FROM (
                       SELECT DISTINCT ON (original_filename) file_path AS fp
                       FROM (
                           SELECT a.original_filename, a.file_path, 1 AS pref
                             FROM public.claim_case_email_attachments a WHERE a.email_id = sh.email_id
                           UNION ALL
                           SELECT d.original_filename, d.file_path, 2 AS pref
                             FROM public.claim_case_documents d WHERE d.sent_email_id = sh.email_id
                       ) u ORDER BY original_filename, pref
                   ) y) AS docs,
                   sh.remarks,
                   sh.created_at
            FROM public.status_history sh
            JOIN public.hospitalization h ON h.id = sh.claim_case_id
            WHERE sh.stage = 'CLAIM'
            WINDOW w AS (PARTITION BY sh.claim_case_id ORDER BY sh.created_at, sh.id)
        ) t
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_track_claim_status ON public.status_history;")
    op.execute("DROP FUNCTION IF EXISTS public.track_claim_status();")
    op.drop_index('ix_claim_status_tracking_hospitalization_id', table_name='claim_status_tracking')
    op.drop_table('claim_status_tracking')
