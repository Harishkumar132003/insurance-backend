from sqlalchemy import Column, BigInteger, String, Integer, Boolean, Date, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
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
    # ICD-10-PCS procedure code for the surgery, AI-suggested in the form.
    surgery_icd_code = Column(String, nullable=True)
    # One treatment can use several routes (IV antibiotics + oral analgesia + a
    # nebuliser), so this is a JSONB array of DRUG_ROUTES codes, e.g.
    # ["IV", "PO", "NEB"]. Legacy rows were single codes and were wrapped into
    # one-element arrays by the startup migration.
    drug_route = Column(JSONB, nullable=True)
    injury_cause = Column(String, nullable=True)
    past_history = Column(Text, nullable=True)
    duration_days = Column(Integer, nullable=True)
    critical_findings = Column(Text, nullable=True)
    treatment_details = Column(Text, nullable=True)
    illness_description = Column(Text, nullable=True)
    first_consultation_date = Column(Date, nullable=True)

    # The repeatable Treatments group: an ordered JSONB array of
    # {treatment_details, drug_route[], surgery_icd_code, injury_cause}. The
    # scalar columns above still hold entry #1's values (and the joined
    # treatment_details) because the Part-C print and cover email read those.
    treatments = Column(JSONB, nullable=True)

    # Requested investigations, revealed by the tp_investigation toggle below.
    # A variable-length list, so it can't be typed columns — stored as an ordered
    # JSONB array of {investigation_category, investigation_name,
    # investigation_description}, matching the form's own field names.
    investigations = Column(JSONB, nullable=True)

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
