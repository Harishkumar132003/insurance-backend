from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class ClaimCaseDocument(Base):
    __tablename__ = "claim_case_documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(BigInteger, ForeignKey("claim_cases.id"), nullable=False)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim_case = relationship("ClaimCase", back_populates="documents")

    __table_args__ = (
        Index("ix_claim_case_documents_claim_case_id", "claim_case_id"),
    )
