from sqlalchemy import Column, BigInteger, String, Text, Interval, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class PreAuthStatusTracking(Base):
    """Pre-auth status-transition log, built for the AI chat.

    One row per PRE_AUTH status change (the first tracked transition is
    DRAFT -> SUBMITTED; the bare initial DRAFT is not logged). Written by a DB
    trigger on status_history — one case (hospitalization_id) has MANY rows.
    """
    __tablename__ = "preauth_status_tracking"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # Non-unique FK — one case maps to many transition rows.
    hospitalization_id = Column(UUID(as_uuid=True), ForeignKey("hospitalization.id"), nullable=False)
    # Denormalised from the case; kept in sync by a trigger.
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=True)
    uhid = Column(String, nullable=True)
    # The email that drove this transition (from status_history.email_id).
    email_id = Column(BigInteger, ForeignKey("claim_case_emails.id"), nullable=True)
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=False)
    # Time spent moving from from_status -> to_status (Postgres interval, exact —
    # use for averages) plus a human-readable form (e.g. "1 day 2 min 20 sec").
    turn_around_time = Column(Interval, nullable=True)
    turn_around_time_text = Column(String, nullable=True)
    # JSON array of attachment paths on the status's email (NULL when none).
    document_link = Column(JSONB, nullable=True)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_preauth_status_tracking_hospitalization_id", "hospitalization_id"),
        Index("ix_preauth_status_tracking_hospital_id", "hospital_id"),
    )
