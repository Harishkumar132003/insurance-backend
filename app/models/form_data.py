from sqlalchemy import Column, BigInteger, String, Text, Numeric, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class FormData(Base):
    # The pre-auth form row. Pre-auth content lives in the typed pre_auth_*
    # children; claim-stage content (bill breakdown + claimed amount + remarks)
    # lives in claim_bill_item + the claimed_amount/remarks columns here. The
    # `stage` column (PRE_AUTH / CLAIM) discriminates the two — fully replacing
    # the old data_json blob.
    __tablename__ = "pre_auth"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(UUID(as_uuid=True), ForeignKey("hospitalization.id"), nullable=True)
    stage = Column(String, nullable=False, default="PRE_AUTH", server_default="PRE_AUTH")
    status = Column(String, nullable=False, default="DRAFT")
    # Claim-stage only (NULL for pre-auth rows).
    claimed_amount = Column(Numeric(12, 2), nullable=True)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    claim_case = relationship("ClaimCase", back_populates="form_data")
    # Structured pre-auth sections (1:1).
    patient = relationship("PreAuthPatient", back_populates="form_data", uselist=False, cascade="all, delete-orphan")
    treatment = relationship("PreAuthTreatment", back_populates="form_data", uselist=False, cascade="all, delete-orphan")
    hospitalization = relationship("PreAuthHospitalization", back_populates="form_data", uselist=False, cascade="all, delete-orphan")
    # Claim-stage bill breakdown lines.
    bill_items = relationship(
        "ClaimBillItem", back_populates="form_data",
        cascade="all, delete-orphan", order_by="ClaimBillItem.sort_order",
    )
