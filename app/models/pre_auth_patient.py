from sqlalchemy import Column, BigInteger, String, Integer, Boolean, Date, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class PreAuthPatient(Base):
    """Structured `patient_insured` section of the pre-auth form. 1:1 with the
    pre-auth form_data row."""
    __tablename__ = "patient_personal_detail"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_data_id = Column(BigInteger, ForeignKey("pre_auth.id", ondelete="CASCADE"), unique=True, nullable=False)
    # Denormalised from the case for easy lookup (source of truth: hospitalization).
    hospitalization_id = Column(UUID(as_uuid=True), ForeignKey("hospitalization.id"), nullable=True)
    uhid = Column(String, nullable=True)

    patient_name = Column(String, nullable=True)
    gender = Column(String, nullable=True)
    address = Column(String, nullable=True)
    age_years = Column(Integer, nullable=True)
    occupation = Column(String, nullable=True)
    employee_id = Column(String, nullable=True)
    date_of_birth = Column(Date, nullable=True)
    policy_number = Column(String, nullable=True)
    contact_number = Column(String, nullable=True)
    corporate_name = Column(String, nullable=True)
    insured_card_id = Column(String, nullable=True)
    has_other_insurance = Column(Boolean, nullable=True)
    has_family_physician = Column(Boolean, nullable=True)
    family_physician_name = Column(String, nullable=True)
    family_physician_contact = Column(String, nullable=True)
    other_insurance_company = Column(String, nullable=True)
    other_insurance_details = Column(String, nullable=True)
    relative_contact_number = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    form_data = relationship("FormData", back_populates="patient")

    __table_args__ = (
        Index("ix_patient_personal_detail_form_data_id", "form_data_id"),
    )
