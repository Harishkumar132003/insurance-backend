from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class ClaimCaseEmailAttachment(Base):
    __tablename__ = "claim_case_email_attachments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    email_id = Column(BigInteger, ForeignKey("claim_case_emails.id"), nullable=False)
    claim_case_id = Column(UUID(as_uuid=True), ForeignKey("claim_cases.id"), nullable=False)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    email = relationship("ClaimCaseEmail", back_populates="attachments")
    claim_case = relationship("ClaimCase")

    __table_args__ = (
        Index("ix_claim_case_email_attachments_email_id", "email_id"),
        Index("ix_claim_case_email_attachments_claim_case_id", "claim_case_id"),
    )
