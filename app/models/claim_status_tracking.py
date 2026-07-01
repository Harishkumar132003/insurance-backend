from sqlalchemy import Column, BigInteger, String, Text, Interval, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class ClaimStatusTracking(Base):
    """Claim-stage status-transition log, built for the AI chat (sibling of
    preauth_status_tracking).

    One row per CLAIM status change; the first row is CLAIM_SUBMITTED
    (from_status NULL). Written by a deferred DB trigger on status_history
    (stage='CLAIM') — one case (hospitalization_id) has MANY rows. `remark`
    carries the claim remark (replacing the old pre_auth.remarks).
    """
    __tablename__ = "claim_status_tracking"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # Non-unique FK — one case maps to many transition rows.
    hospitalization_id = Column(UUID(as_uuid=True), ForeignKey("hospitalization.id"), nullable=False)
    # Denormalised from the case; kept in sync by a trigger.
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=True)
    uhid = Column(String, nullable=True)
    claim_number = Column(String, nullable=True)
    # The email that drove this transition (from status_history.email_id).
    email_id = Column(BigInteger, ForeignKey("claim_case_emails.id"), nullable=True)
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=False)
    # Time spent from_status -> to_status (interval, exact) + readable form.
    turn_around_time = Column(Interval, nullable=True)
    turn_around_time_text = Column(String, nullable=True)
    # JSON array of file paths on the status's email (attachments + uploaded
    # case documents, deduped by filename); NULL when none.
    document_link = Column(JSONB, nullable=True)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_claim_status_tracking_hospitalization_id", "hospitalization_id"),
        Index("ix_claim_status_tracking_hospital_id", "hospital_id"),
    )
