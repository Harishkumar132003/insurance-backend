from sqlalchemy import Column, BigInteger, String, Integer, Boolean, Date, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class PreAuthTreatment(Base):
    """Structured `treating_doctor` section (+ flattened treatment_plan and
    accident_details). 1:1 with the pre-auth form_data row."""
    __tablename__ = "pre_auth_treatment"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_data_id = Column(BigInteger, ForeignKey("pre_auth.id", ondelete="CASCADE"), unique=True, nullable=False)

    doctor_name = Column(String, nullable=True)
    provisional_diagnosis = Column(String, nullable=True)
    icd10_code = Column(String, nullable=True)
    surgery_name = Column(String, nullable=True)
    surgery_icd_code = Column(String, nullable=True)
    drug_route = Column(String, nullable=True)
    injury_cause = Column(String, nullable=True)
    past_history = Column(Text, nullable=True)
    duration_days = Column(Integer, nullable=True)
    other_treatment = Column(Text, nullable=True)
    critical_findings = Column(Text, nullable=True)
    treatment_details = Column(Text, nullable=True)
    illness_description = Column(Text, nullable=True)
    first_consultation_date = Column(Date, nullable=True)

    # treatment_plan.*
    tp_investigation = Column(Boolean, nullable=True)
    tp_intensive_care = Column(Boolean, nullable=True)
    tp_non_allopathic = Column(Boolean, nullable=True)
    tp_medical_management = Column(Boolean, nullable=True)
    tp_surgical_management = Column(Boolean, nullable=True)

    # accident_details.*
    ad_is_rta = Column(Boolean, nullable=True)
    ad_substance_abuse = Column(Boolean, nullable=True)
    ad_reported_to_police = Column(Boolean, nullable=True)
    ad_test_conducted = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    form_data = relationship("FormData", back_populates="treatment")

    __table_args__ = (
        Index("ix_pre_auth_treatment_form_data_id", "form_data_id"),
    )
