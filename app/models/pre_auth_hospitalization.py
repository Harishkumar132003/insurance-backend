from sqlalchemy import Column, BigInteger, String, Integer, Boolean, Date, Numeric, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class PreAuthHospitalization(Base):
    """Structured `hospitalization` section of the pre-auth form (+ flattened
    costs and chronic_conditions). 1:1 with the pre-auth form_data row.

    Table renamed to `pre_auth_stay` to free the bare `hospitalization` name
    for the hub case table; model class kept to avoid touching readers.
    """
    __tablename__ = "pre_auth_stay"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_data_id = Column(BigInteger, ForeignKey("pre_auth.id", ondelete="CASCADE"), unique=True, nullable=False)

    room_type = Column(String, nullable=True)
    is_emergency = Column(Boolean, nullable=True)
    icu_days = Column(Integer, nullable=True)
    expected_days = Column(Integer, nullable=True)
    admission_date = Column(Date, nullable=True)
    admission_time = Column(String, nullable=True)

    # costs.*
    room_rent = Column(Numeric(12, 2), nullable=True)
    ot_charges = Column(Numeric(12, 2), nullable=True)
    icu_charges = Column(Numeric(12, 2), nullable=True)
    medicines_cost = Column(Numeric(12, 2), nullable=True)
    investigation_cost = Column(Numeric(12, 2), nullable=True)
    professional_fees = Column(Numeric(12, 2), nullable=True)
    package_charges = Column(Numeric(12, 2), nullable=True)
    other_expenses = Column(Numeric(12, 2), nullable=True)
    total_cost = Column(Numeric(12, 2), nullable=True)
    # Room costs derived server-side on save (per-day rate * days):
    #   room_rent_total   = room_rent   (per day) * non-ICU days (expected - icu)
    #   icu_charges_total = icu_charges (per day) * ICU days
    room_rent_total = Column(Numeric(12, 2), nullable=True)
    icu_charges_total = Column(Numeric(12, 2), nullable=True)

    # chronic_conditions.*
    cc_diabetes = Column(Boolean, nullable=True)
    cc_hypertension = Column(Boolean, nullable=True)
    cc_heart_disease = Column(Boolean, nullable=True)
    cc_asthma_copd = Column(Boolean, nullable=True)
    cc_cancer = Column(Boolean, nullable=True)
    cc_hiv_std = Column(Boolean, nullable=True)
    cc_hyperlipidemia = Column(Boolean, nullable=True)
    cc_osteoarthritis = Column(Boolean, nullable=True)
    cc_alcohol_drug_abuse = Column(Boolean, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    form_data = relationship("FormData", back_populates="hospitalization")

    __table_args__ = (
        Index("ix_pre_auth_stay_form_data_id", "form_data_id"),
    )
