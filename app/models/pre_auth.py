from sqlalchemy import Column, BigInteger, String, Text, Numeric, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class PreAuth(Base):
    __tablename__ = "pre_auths"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(BigInteger, ForeignKey("claim_cases.id"), unique=True, nullable=False)
    form_data_id = Column(BigInteger, ForeignKey("form_data.id"), nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    request_date = Column(DateTime(timezone=True), server_default=func.now())
    response_date = Column(DateTime(timezone=True), nullable=True)
    approved_amount = Column(Numeric(12, 2), nullable=True)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim_case = relationship("ClaimCase", back_populates="pre_auth")
    form_data = relationship("FormData")

    __table_args__ = (
        Index("ix_pre_auths_claim_case_id", "claim_case_id"),
    )
