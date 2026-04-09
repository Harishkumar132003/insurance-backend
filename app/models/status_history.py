from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class StatusHistory(Base):
    __tablename__ = "status_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(UUID(as_uuid=True), ForeignKey("claim_cases.id"), nullable=False)
    stage = Column(String, nullable=False)
    status = Column(String, nullable=False)
    remarks = Column(Text, nullable=True)
    changed_by = Column(String, nullable=True)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim_case = relationship("ClaimCase", back_populates="status_history")
    user = relationship("User")

    __table_args__ = (
        Index("ix_status_history_claim_case_id", "claim_case_id"),
    )
