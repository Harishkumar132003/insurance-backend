from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class FormData(Base):
    # The pre-auth form row (always pre-auth — claim-stage data lives elsewhere:
    # bill lines in claim_bill_item keyed by the case, claim totals on the claims
    # row). Pre-auth content lives in the typed pre_auth_* children.
    __tablename__ = "pre_auth"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # DB column is `hospitalization_id` (FK -> hospitalization.id); the ORM
    # attribute stays `claim_case_id` so existing code/queries are unaffected.
    claim_case_id = Column("hospitalization_id", UUID(as_uuid=True), ForeignKey("hospitalization.id"), nullable=True)
    # The case's pre-auth workflow status, mirrored onto this PRE_AUTH row from
    # hospitalization.case_status while current_stage='PRE_AUTH', then FROZEN once
    # the claim is raised. Kept in sync by a DB trigger (trg_sync_preauth_status),
    # not app code. Read-only from the app's perspective.
    preauth_status = Column(String, nullable=False, default="DRAFT", server_default="DRAFT")
    # Convenience mirrors for easy reading on one row (source of truth elsewhere):
    #   preauth_raised_amount   = original pre-auth requested amount
    #     (= pre_auth_stay.total_cost; set on form save).
    #   preauth_approved_amount = pre-auth approved amount
    #     (= hospitalization.approved_amount; set on approval).
    preauth_raised_amount = Column(Numeric(12, 2), nullable=True)
    preauth_approved_amount = Column(Numeric(12, 2), nullable=True)
    # Denormalised from the case (hospitalization.hospital_id); kept in sync by a trigger.
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    claim_case = relationship("ClaimCase", back_populates="form_data")

    __table_args__ = (
        Index("ix_pre_auth_hospital_id", "hospital_id"),
    )
    # Structured pre-auth sections (1:1).
    patient = relationship("PreAuthPatient", back_populates="form_data", uselist=False, cascade="all, delete-orphan")
    treatment = relationship("PreAuthTreatment", back_populates="form_data", uselist=False, cascade="all, delete-orphan")
    hospitalization = relationship("PreAuthHospitalization", back_populates="form_data", uselist=False, cascade="all, delete-orphan")
