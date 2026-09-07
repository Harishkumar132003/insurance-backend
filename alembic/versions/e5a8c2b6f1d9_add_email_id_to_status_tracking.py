"""map claim_case_emails to preauth_status_tracking via email_id

Adds preauth_status_tracking.email_id (FK -> claim_case_emails.id), sourced from
status_history.email_id — the email that drove each transition. Lets the AI join
a status change to its email (type, subject, ai_suggested_*). Updates the trigger
function to populate it and backfills existing rows.

Revision ID: e5a8c2b6f1d9
Revises: d4f7b1e3c8a2
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op

revision = 'e5a8c2b6f1d9'
down_revision = 'd4f7b1e3c8a2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('preauth_status_tracking', sa.Column('email_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_preauth_status_tracking_email', 'preauth_status_tracking',
        'claim_case_emails', ['email_id'], ['id'],
    )

    # Recreate the trigger function to also record the status email id.
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

    # Backfill email_id from the source status_history row (matched on case +
    # exact created_at + status, which the tracking rows copied verbatim).
    op.execute("""
        UPDATE public.preauth_status_tracking t
           SET email_id = sh.email_id
          FROM public.status_history sh
         WHERE sh.claim_case_id = t.hospitalization_id
           AND sh.stage = 'PRE_AUTH'
           AND sh.created_at = t.created_at
           AND sh.status = t.to_status
    """)


def downgrade():
    # Restore the trigger function without email_id.
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
    op.drop_constraint('fk_preauth_status_tracking_email', 'preauth_status_tracking', type_='foreignkey')
    op.drop_column('preauth_status_tracking', 'email_id')
