"""dedupe document_link by original_filename

On submit, the uploaded document is also attached to the outgoing email, so the
SAME file exists in both claim_case_documents and claim_case_email_attachments
(same original_filename, different stored path). Combining both double-counted it.
Now we dedupe by original_filename (one path per logical file), still covering
both sources for genuinely different files.

Revision ID: a7c1e4b8d2f5
Revises: f6b9d3a1c4e7
Create Date: 2026-06-26
"""
from alembic import op

revision = 'a7c1e4b8d2f5'
down_revision = 'f6b9d3a1c4e7'
branch_labels = None
depends_on = None


def upgrade():
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
        -- email attachments + uploaded case_documents, deduped by original_filename
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
        INSERT INTO public.preauth_status_tracking
            (hospitalization_id, uhid, email_id, from_status, to_status, turn_around_time,
             turn_around_time_text, document_link, remark, created_at)
        VALUES
            (NEW.claim_case_id, v_uhid, NEW.email_id, prev_status, NEW.status, v_tat,
             public.format_tat(v_tat), v_docs, NEW.remarks, NEW.created_at);
        RETURN NEW;
    END;
    $func$;
    """)

    # Recompute existing rows with the deduped logic.
    op.execute("""
        UPDATE public.preauth_status_tracking t
           SET document_link = (
               SELECT jsonb_agg(fp ORDER BY fp) FROM (
                   SELECT DISTINCT ON (original_filename) file_path AS fp
                   FROM (
                       SELECT a.original_filename, a.file_path, 1 AS pref
                         FROM public.claim_case_email_attachments a WHERE a.email_id = t.email_id
                       UNION ALL
                       SELECT d.original_filename, d.file_path, 2 AS pref
                         FROM public.claim_case_documents d WHERE d.sent_email_id = t.email_id
                   ) u
                   ORDER BY original_filename, pref
               ) y
           )
         WHERE t.email_id IS NOT NULL
    """)


def downgrade():
    # Restore the non-deduped (UNION of all paths) logic + recompute.
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
        SELECT jsonb_agg(fp ORDER BY fp) INTO v_docs FROM (
            SELECT a.file_path AS fp FROM public.claim_case_email_attachments a WHERE a.email_id = NEW.email_id
            UNION
            SELECT d.file_path     FROM public.claim_case_documents d        WHERE d.sent_email_id = NEW.email_id
        ) x;
        v_tat := CASE WHEN prev_time IS NOT NULL THEN NEW.created_at - prev_time ELSE NULL END;
        INSERT INTO public.preauth_status_tracking
            (hospitalization_id, uhid, email_id, from_status, to_status, turn_around_time,
             turn_around_time_text, document_link, remark, created_at)
        VALUES
            (NEW.claim_case_id, v_uhid, NEW.email_id, prev_status, NEW.status, v_tat,
             public.format_tat(v_tat), v_docs, NEW.remarks, NEW.created_at);
        RETURN NEW;
    END;
    $func$;
    """)
    op.execute("""
        UPDATE public.preauth_status_tracking t
           SET document_link = (
               SELECT jsonb_agg(fp ORDER BY fp) FROM (
                   SELECT a.file_path AS fp FROM public.claim_case_email_attachments a WHERE a.email_id = t.email_id
                   UNION
                   SELECT d.file_path     FROM public.claim_case_documents d        WHERE d.sent_email_id = t.email_id
               ) x
           )
         WHERE t.email_id IS NOT NULL
    """)
