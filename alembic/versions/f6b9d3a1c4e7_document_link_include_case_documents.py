"""document_link = email attachments + uploaded case_documents

Previously document_link held only claim_case_email_attachments for the status's
email. Now it also includes claim_case_documents sent on that email (the
hospital's uploaded/sent supporting docs), deduped. Updates the trigger function
and recomputes existing rows (via their email_id).

Revision ID: f6b9d3a1c4e7
Revises: e5a8c2b6f1d9
Create Date: 2026-06-26
"""
from alembic import op

revision = 'f6b9d3a1c4e7'
down_revision = 'e5a8c2b6f1d9'
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
        -- email attachments + uploaded case_documents on this status's email
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

    # Recompute existing rows' document_link from both sources via their email_id.
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


def downgrade():
    # Restore attachments-only document logic + recompute.
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
               SELECT jsonb_agg(a.file_path ORDER BY a.id)
                 FROM public.claim_case_email_attachments a WHERE a.email_id = t.email_id
           )
         WHERE t.email_id IS NOT NULL
    """)
