from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(BigInteger, ForeignKey("claim_cases.id"), nullable=False)
    query_type = Column(String, nullable=False)  # QUERY / ADR
    query_details = Column(Text, nullable=True)
    documents_requested = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="OPEN")  # OPEN / RESOLVED
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim_case = relationship("ClaimCase", back_populates="query_logs")

    __table_args__ = (
        Index("ix_query_logs_claim_case_id", "claim_case_id"),
    )
