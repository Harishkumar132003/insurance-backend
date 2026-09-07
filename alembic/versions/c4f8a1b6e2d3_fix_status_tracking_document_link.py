"""fix document_link: keep all uploaded docs, drop only true duplicates

The filename dedup over-collapsed genuinely-different uploaded documents that
share a filename (e.g. the same PDF uploaded under two document_types). New rule:
take ALL claim_case_documents for the status's email (authoritative, by id), plus
only the email attachments whose filename is NOT among those documents (i.e. not a
sent copy). Centralised in status_email_docs(); applied to both tracking tables'
triggers and backfilled.

Revision ID: c4f8a1b6e2d3
Revises: b9e2d5f8a3c1
Create Date: 2026-06-26
"""
from alembic import op

revision = 'c4f8a1b6e2d3'
down_revision = 'b9e2d5f8a3c1'
branch_labels = None
depends_on = None


def upgrade():
    # Shared helper: uploaded docs (all) + attachments that aren't a copy.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.status_email_docs(eid bigint) RETURNS jsonb
    LANGUAGE sql STABLE AS $func$
        SELECT jsonb_agg(fp ORDER BY fp) FROM (
            SELECT d.file_path AS fp
              FROM public.claim_case_documents d
             WHERE d.sent_email_id = eid
            UNION ALL
            SELECT a.file_path
              FROM public.claim_case_email_attachments a
             WHERE a.email_id = eid
               AND a.original_filename NOT IN (
                   SELECT d.original_filename
                     FROM public.claim_case_documents d
                    WHERE d.sent_email_id = eid
               )
        ) x
    $func$;
    """)

    # Repoint both trigger functions at the helper for document_link.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.track_preauth_status() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    DECLARE
        prev_status varchar; prev_time timestamptz; v_uhid varchar; v_docs jsonb; v_tat interval;
    BEGIN
        IF NEW.stage <> 'PRE_AUTH' THEN RETURN NEW; END IF;
        IF NEW.status = 'DRAFT' THEN RETURN NEW; END IF;
        SELECT sh.status, sh.created_at INTO prev_status, prev_time
          FROM public.status_history sh
         WHERE sh.claim_case_id = NEW.claim_case_id AND sh.stage = 'PRE_AUTH' AND sh.id <> NEW.id
         ORDER BY sh.created_at DESC, sh.id DESC LIMIT 1;
        SELECT uhid INTO v_uhid FROM public.hospitalization WHERE id = NEW.claim_case_id;
        v_docs := public.status_email_docs(NEW.email_id);
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
    CREATE OR REPLACE FUNCTION public.track_claim_status() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    DECLARE
        prev_status varchar; prev_time timestamptz; v_uhid varchar; v_claimno varchar; v_docs jsonb; v_tat interval;
    BEGIN
        IF NEW.stage <> 'CLAIM' THEN RETURN NEW; END IF;
        SELECT sh.status, sh.created_at INTO prev_status, prev_time
          FROM public.status_history sh
         WHERE sh.claim_case_id = NEW.claim_case_id AND sh.stage = 'CLAIM' AND sh.id <> NEW.id
         ORDER BY sh.created_at DESC, sh.id DESC LIMIT 1;
        SELECT uhid, claim_number INTO v_uhid, v_claimno
          FROM public.hospitalization WHERE id = NEW.claim_case_id;
        v_docs := public.status_email_docs(NEW.email_id);
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

    # Backfill both tables with the corrected document_link.
    op.execute("UPDATE public.preauth_status_tracking SET document_link = public.status_email_docs(email_id) WHERE email_id IS NOT NULL")
    op.execute("UPDATE public.claim_status_tracking   SET document_link = public.status_email_docs(email_id) WHERE email_id IS NOT NULL")


def downgrade():
    # No-op: the corrected document_link logic is strictly better, and the trigger
    # functions still reference status_email_docs(), so we keep it in place.
    pass
