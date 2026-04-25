from sqlalchemy import Column, BigInteger, Boolean, String, Text, DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class ClaimCaseEmail(Base):
    __tablename__ = "claim_case_emails"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(UUID(as_uuid=True), ForeignKey("claim_cases.id"), nullable=False)
    direction = Column(String, nullable=False)  # "SENT" or "RECEIVED"
    from_email = Column(String, nullable=False)
    to_email = Column(String, nullable=False)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    message_id = Column(String, unique=True, nullable=True)
    email_type = Column(String, nullable=True)  # SUBMITTED, ENHANCE_SUBMITTED, RECONSIDER, ADR_SUBMITTED, APPROVAL, PARTIAL_APPROVAL, DENIAL, ADR_NMI
    thread_id = Column(String, nullable=True)
    email_date = Column(DateTime(timezone=True), nullable=True)

    # AI suggestion & validation fields
    is_read = Column(Boolean, nullable=False, default=False, server_default="false")
    # Read state for the in-app insurance-provider user. Always true for
    # external (non-onboarded) providers — there is no in-app reader to track.
    provider_read = Column(Boolean, nullable=False, default=True, server_default="true")
    ai_suggested_status = Column(String, nullable=True)
    ai_suggested_amount = Column(Numeric(12, 2), nullable=True)
    ai_suggested_claim_number = Column(String, nullable=True)
    ai_summary = Column(Text, nullable=True)
    ai_query_details = Column(Text, nullable=True)
    ai_documents_requested = Column(Text, nullable=True)
    validation_status = Column(String, nullable=False, default="PENDING", server_default="PENDING")
    validated_at = Column(DateTime(timezone=True), nullable=True)
    validated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim_case = relationship("ClaimCase", back_populates="emails")
    attachments = relationship(
        "ClaimCaseEmailAttachment",
        back_populates="email",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_claim_case_emails_claim_case_id", "claim_case_id"),
        Index("ix_claim_case_emails_message_id", "message_id"),
    )
