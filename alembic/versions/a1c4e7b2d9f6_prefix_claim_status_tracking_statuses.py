"""prefix claim_status_tracking statuses with CLAIM_

status_history stores claim-stage statuses bare (SUBMITTED, APPROVED, ...),
ambiguous with pre-auth. Normalise from_status/to_status in claim_status_tracking
to be CLAIM_-prefixed via an idempotent helper (claim_status_label): prefix only
if not already starting with CLAIM_. Applies to the trigger (future rows) and a
backfill (existing rows).

Revision ID: a1c4e7b2d9f6
Revises: f3b7d2a9c5e8
Create Date: 2026-06-26
"""
from alembic import op

revision = 'a1c4e7b2d9f6'
down_revision = 'f3b7d2a9c5e8'
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent label helper: CLAIM_-prefix unless already prefixed (NULL-safe).
    op.execute("""
    CREATE OR REPLACE FUNCTION public.claim_status_label(s varchar) RETURNS varchar
    LANGUAGE sql IMMUTABLE AS $func$
        SELECT CASE
            WHEN s IS NULL THEN NULL
            WHEN starts_with(s, 'CLAIM_') THEN s
            ELSE 'CLAIM_' || s
        END
    $func$;
    """)

    # Recreate the trigger function to label from_status / to_status.
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
            (NEW.claim_case_id, v_uhid, v_claimno, NEW.email_id,
             public.claim_status_label(prev_status), public.claim_status_label(NEW.status),
             v_tat, public.format_tat(v_tat), v_docs, NEW.remarks, NEW.created_at);
        RETURN NEW;
    END;
    $func$;
    """)

    # Backfill existing rows (idempotent).
    op.execute("""
        UPDATE public.claim_status_tracking
           SET from_status = public.claim_status_label(from_status),
               to_status   = public.claim_status_label(to_status)
    """)


def downgrade():
    # Restore the un-labeled trigger function; existing data is left prefixed.
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
    op.execute("DROP FUNCTION IF EXISTS public.claim_status_label(varchar);")
