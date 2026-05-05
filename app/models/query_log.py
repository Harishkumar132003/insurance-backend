from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(UUID(as_uuid=True), ForeignKey("claim_cases.id"), nullable=False)
    query_type = Column(String, nullable=False)  # ADR_NMI (additional docs / need more info)
    query_details = Column(Text, nullable=True)
    documents_requested = Column(Text, nullable=True)
    # Structured list (AI-extracted) of document names being requested.
    documents_list = Column(JSONB, nullable=True)
    status = Column(String, nullable=False, default="OPEN")  # OPEN / RESOLVED
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim_case = relationship("ClaimCase", back_populates="query_logs")

    __table_args__ = (
        Index("ix_query_logs_claim_case_id", "claim_case_id"),
    )
