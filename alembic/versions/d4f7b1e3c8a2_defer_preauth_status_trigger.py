"""make preauth status-tracking trigger DEFERRED

The app inserts the status_history row BEFORE the email's attachment (same
transaction, e.g. process_by_provider). A normal AFTER INSERT trigger therefore
ran before the attachment existed, leaving document_link empty for new flows.
Recreate the trigger as a DEFERRABLE INITIALLY DEFERRED constraint trigger so it
fires at COMMIT, by which time all same-transaction rows (attachments) exist.

Revision ID: d4f7b1e3c8a2
Revises: c3e6a9b2d5f1
Create Date: 2026-06-26
"""
from alembic import op

revision = 'd4f7b1e3c8a2'
down_revision = 'c3e6a9b2d5f1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_track_preauth_status ON public.status_history;")
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_track_preauth_status
        AFTER INSERT ON public.status_history
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION public.track_preauth_status();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_track_preauth_status ON public.status_history;")
    op.execute("""
        CREATE TRIGGER trg_track_preauth_status
        AFTER INSERT ON public.status_history
        FOR EACH ROW EXECUTE FUNCTION public.track_preauth_status();
    """)
