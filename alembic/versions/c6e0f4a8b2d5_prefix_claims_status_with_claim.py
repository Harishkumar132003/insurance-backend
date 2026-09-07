"""prefix claims.status values with CLAIM_

Makes claims.status consistent with hospitalization.case_status and
claim_status_tracking (which are CLAIM_-prefixed at the claim stage). The claims
table is claim-stage only, so every value is prefixed. Idempotent: only rows not
already prefixed are updated. New rows are written prefixed by the controllers
(see claim_status_value) and the model default (CLAIM_SUBMITTED).

Revision ID: c6e0f4a8b2d5
Revises: b5d9c3e7a1f2
Create Date: 2026-07-06
"""
from alembic import op

revision = 'c6e0f4a8b2d5'
down_revision = 'b5d9c3e7a1f2'
branch_labels = None
depends_on = None


def upgrade():
    # Data migration only. Future rows are written prefixed by the ORM default
    # (CLAIM_SUBMITTED) and the controllers (claim_status_value), so no DB
    # server_default is added (keeps the column in sync with the model).
    op.execute("""
        UPDATE claims
           SET status = 'CLAIM_' || status
         WHERE status IS NOT NULL
           AND status NOT LIKE 'CLAIM_%'
    """)


def downgrade():
    op.execute("""
        UPDATE claims
           SET status = regexp_replace(status, '^CLAIM_', '')
         WHERE status LIKE 'CLAIM_%'
    """)
