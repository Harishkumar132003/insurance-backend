from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Claim(Base):
    __tablename__ = "claims"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(UUID(as_uuid=True), ForeignKey("claim_cases.id"), unique=True, nullable=False)
    claimed_amount = Column(Numeric(12, 2), nullable=False)
    approved_amount = Column(Numeric(12, 2), nullable=True)
    status = Column(String, nullable=False, default="SUBMITTED")
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim_case = relationship("ClaimCase", back_populates="claim")
    settlement = relationship("Settlement", back_populates="claim", uselist=False)

    __table_args__ = (
        Index("ix_claims_claim_case_id", "claim_case_id"),
    )
