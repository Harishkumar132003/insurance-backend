"""add turn_around_time_text (human-readable TAT) to preauth_status_tracking

Adds a readable string form of turn_around_time, e.g. "1 day 2 min 20 sec",
"5 min 2 sec", "55 sec" (zero parts omitted). The interval column is kept for
exact aggregation. A format_tat(interval) SQL helper renders it, used by both
the trigger and the backfill.

Revision ID: c3e6a9b2d5f1
Revises: b1d4f7a2c9e3
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op

revision = 'c3e6a9b2d5f1'
down_revision = 'b1d4f7a2c9e3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('preauth_status_tracking', sa.Column('turn_around_time_text', sa.String(), nullable=True))

    # Render an interval as "1 day 2 min 20 sec" (omitting zero components).
    op.execute("""
    CREATE OR REPLACE FUNCTION public.format_tat(iv interval) RETURNS text
    LANGUAGE sql IMMUTABLE AS $func$
        SELECT CASE WHEN iv IS NULL THEN NULL ELSE
            COALESCE(NULLIF(trim(concat_ws(' ',
                CASE WHEN EXTRACT(DAY    FROM iv)::int > 0
                     THEN EXTRACT(DAY FROM iv)::int || ' day' ||
                          CASE WHEN EXTRACT(DAY FROM iv)::int > 1 THEN 's' ELSE '' END END,
                CASE WHEN EXTRACT(HOUR   FROM iv)::int > 0 THEN EXTRACT(HOUR FROM iv)::int || ' hr' END,
                CASE WHEN EXTRACT(MINUTE FROM iv)::int > 0 THEN EXTRACT(MINUTE FROM iv)::int || ' min' END,
                CASE WHEN floor(EXTRACT(SECOND FROM iv))::int > 0 THEN floor(EXTRACT(SECOND FROM iv))::int || ' sec' END
            )), ''), '0 sec')
        END
    $func$;
    """)

    # Recreate the tracking trigger to also populate the text form.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.track_preauth_status() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    DECLARE
        prev_status varchar;
        prev_time   timestamptz;
        v_uhid      varchar;
        v_docs      jsonb;
        v_tat       interval;
    BEGIN
        IF NEW.stage <> 'PRE_AUTH' THEN RETURN NEW; END IF;
        IF NEW.status = 'DRAFT' THEN RETURN NEW; END IF;
        SELECT sh.status, sh.created_at INTO prev_status, prev_time
          FROM public.status_history sh
         WHERE sh.claim_case_id = NEW.claim_case_id AND sh.stage = 'PRE_AUTH' AND sh.id <> NEW.id
         ORDER BY sh.created_at DESC, sh.id DESC
         LIMIT 1;
        SELECT uhid INTO v_uhid FROM public.hospitalization WHERE id = NEW.claim_case_id;
        SELECT jsonb_agg(a.file_path ORDER BY a.id) INTO v_docs
          FROM public.claim_case_email_attachments a WHERE a.email_id = NEW.email_id;
        v_tat := CASE WHEN prev_time IS NOT NULL THEN NEW.created_at - prev_time ELSE NULL END;
        INSERT INTO public.preauth_status_tracking
            (hospitalization_id, uhid, from_status, to_status, turn_around_time,
             turn_around_time_text, document_link, remark, created_at)
        VALUES
            (NEW.claim_case_id, v_uhid, prev_status, NEW.status, v_tat,
             public.format_tat(v_tat), v_docs, NEW.remarks, NEW.created_at);
        RETURN NEW;
    END;
    $func$;
    """)

    # Backfill the text for existing rows.
    op.execute("UPDATE public.preauth_status_tracking SET turn_around_time_text = public.format_tat(turn_around_time)")


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS public.format_tat(interval);")
    # Restore the trigger function without the text column.
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
        IF NEW.status = 'DRAFT' THEN RETURN NEW; END IF;
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
    op.drop_column('preauth_status_tracking', 'turn_around_time_text')
