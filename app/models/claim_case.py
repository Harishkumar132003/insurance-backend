import uuid

from sqlalchemy import Column, Numeric, String, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class ClaimCase(Base):
    __tablename__ = "claim_cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    uhid = Column(String, nullable=False)
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=True)
    policy_provider_id = Column(UUID(as_uuid=True), ForeignKey("policy_provider_configs.id"), nullable=False)
    claim_number = Column(String, nullable=True)
    current_stage = Column(String, nullable=False, default="PRE_AUTH")
    status = Column(String, nullable=False, default="DRAFT")
    claim_status = Column(String, nullable=True)
    approved_amount = Column(Numeric(12, 2), nullable=True)
    thread_id = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    pre_auth = relationship("PreAuth", back_populates="claim_case", uselist=False)
    claim = relationship("Claim", back_populates="claim_case", uselist=False)
    status_history = relationship("StatusHistory", back_populates="claim_case")
    form_data = relationship("FormData", back_populates="claim_case")
    query_logs = relationship("QueryLog", back_populates="claim_case")
    emails = relationship("ClaimCaseEmail", back_populates="claim_case", order_by="ClaimCaseEmail.created_at")
    documents = relationship("ClaimCaseDocument", back_populates="claim_case", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_claim_cases_uhid", "uhid"),
    )
