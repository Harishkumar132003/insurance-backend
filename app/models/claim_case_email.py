from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class ClaimCaseEmail(Base):
    __tablename__ = "claim_case_emails"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(BigInteger, ForeignKey("claim_cases.id"), nullable=False)
    direction = Column(String, nullable=False)  # "SENT" or "RECEIVED"
    from_email = Column(String, nullable=False)
    to_email = Column(String, nullable=False)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    message_id = Column(String, unique=True, nullable=True)
    email_type = Column(String, nullable=True)  # QUERY_RAISED, QUERY_RESPONSE, APPROVAL, REJECTION, ADR
    thread_id = Column(String, nullable=True)
    email_date = Column(DateTime(timezone=True), nullable=True)
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
