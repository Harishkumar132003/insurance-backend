from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Claim(Base):
    __tablename__ = "claims"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # DB column is `hospitalization_id` (FK -> hospitalization.id); the ORM
    # attribute stays `claim_case_id` so existing code/queries are unaffected.
    claim_case_id = Column("hospitalization_id", UUID(as_uuid=True), ForeignKey("hospitalization.id"), unique=True, nullable=False)
    # Denormalised from the case for easy lookup (source of truth: hospitalization).
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=True)
    uhid = Column(String, nullable=True)
    claim_number = Column(String, nullable=True)
    claimed_amount = Column(Numeric(12, 2), nullable=False)
    approved_amount = Column(Numeric(12, 2), nullable=True)
    status = Column(String, nullable=False, default="SUBMITTED")
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim_case = relationship("ClaimCase", back_populates="claim")

    __table_args__ = (
        Index("ix_claims_hospitalization_id", claim_case_id),
        Index("ix_claims_hospital_id", "hospital_id"),
    )
