"""rename claim statuses to new flow

Revision ID: f7a3b2c9d1e4
Revises: c1d2e3f4a5b6
Create Date: 2026-04-21 00:00:00.000000

Backfill only — no schema change. Aligns existing rows with the new claim
workflow states (see app/controllers/claim_case_controller.py):
    APPLIED            -> SUBMITTED
    REJECTED           -> DENIED
    ADR, QUERY         -> ADR_NMI
email_type values:
    APPLIED            -> SUBMITTED
    REJECTION          -> DENIAL
    ADR, QUERY_RAISED  -> ADR_NMI
query_logs.query_type:
    QUERY, ADR         -> ADR_NMI
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f7a3b2c9d1e4'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # claim_cases.status (workflow)
    op.execute("UPDATE claim_cases SET status = 'SUBMITTED' WHERE status = 'APPLIED'")
    op.execute("UPDATE claim_cases SET status = 'DENIED'    WHERE status = 'REJECTED'")
    op.execute("UPDATE claim_cases SET status = 'ADR_NMI'   WHERE status IN ('ADR', 'QUERY')")

    # claim_cases.claim_status (outcome)
    op.execute("UPDATE claim_cases SET claim_status = 'DENIED'  WHERE claim_status = 'REJECTED'")
    op.execute("UPDATE claim_cases SET claim_status = 'ADR_NMI' WHERE claim_status IN ('ADR', 'QUERY')")

    # status_history.status
    op.execute("UPDATE status_history SET status = 'SUBMITTED' WHERE status = 'APPLIED'")
    op.execute("UPDATE status_history SET status = 'DENIED'    WHERE status = 'REJECTED'")
    op.execute("UPDATE status_history SET status = 'ADR_NMI'   WHERE status IN ('ADR', 'QUERY', 'QUERY_RAISED')")

    # claim_case_emails.email_type
    op.execute("UPDATE claim_case_emails SET email_type = 'SUBMITTED'        WHERE email_type = 'APPLIED'")
    op.execute("UPDATE claim_case_emails SET email_type = 'DENIAL'           WHERE email_type = 'REJECTION'")
    op.execute("UPDATE claim_case_emails SET email_type = 'ADR_NMI'          WHERE email_type IN ('ADR', 'QUERY_RAISED')")

    # query_logs.query_type
    op.execute("UPDATE query_logs SET query_type = 'ADR_NMI' WHERE query_type IN ('QUERY', 'ADR')")


def downgrade() -> None:
    # Best-effort reversal. The QUERY vs ADR distinction was collapsed on the
    # way up, so the downgrade restores to 'ADR' (the more common value) and
    # does not attempt to distinguish PARTIALLY_APPROVED (new state) from
    # APPROVED — callers must handle that manually if needed.
    op.execute("UPDATE query_logs SET query_type = 'ADR' WHERE query_type = 'ADR_NMI'")

    op.execute("UPDATE claim_case_emails SET email_type = 'ADR'       WHERE email_type = 'ADR_NMI'")
    op.execute("UPDATE claim_case_emails SET email_type = 'REJECTION' WHERE email_type = 'DENIAL'")
    op.execute("UPDATE claim_case_emails SET email_type = 'APPLIED'   WHERE email_type = 'SUBMITTED'")

    op.execute("UPDATE status_history SET status = 'ADR'      WHERE status = 'ADR_NMI'")
    op.execute("UPDATE status_history SET status = 'REJECTED' WHERE status = 'DENIED'")
    op.execute("UPDATE status_history SET status = 'APPLIED'  WHERE status = 'SUBMITTED'")

    op.execute("UPDATE claim_cases SET claim_status = 'ADR'      WHERE claim_status = 'ADR_NMI'")
    op.execute("UPDATE claim_cases SET claim_status = 'REJECTED' WHERE claim_status = 'DENIED'")

    op.execute("UPDATE claim_cases SET status = 'ADR'      WHERE status = 'ADR_NMI'")
    op.execute("UPDATE claim_cases SET status = 'REJECTED' WHERE status = 'DENIED'")
    op.execute("UPDATE claim_cases SET status = 'APPLIED'  WHERE status = 'SUBMITTED'")
    # Re-submission workflow states (ENHANCE_SUBMITTED / RECONSIDER / ADR_SUBMITTED)
    # did not exist pre-upgrade; collapse them back to the closest prior state.
    op.execute("UPDATE claim_cases SET status = 'APPLIED' WHERE status IN ('ENHANCE_SUBMITTED', 'RECONSIDER', 'ADR_SUBMITTED')")
