import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class HospitalProviderMapping(Base):
    __tablename__ = "hospital_provider_mappings"
    __table_args__ = (
        UniqueConstraint("hospital_id", "policy_provider_id", name="uq_hospital_provider"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=False)
    policy_provider_id = Column(
        UUID(as_uuid=True), ForeignKey("policy_provider_configs.id"), nullable=False
    )
    # Charges parsed from the MOU and reviewed by the admin. Shape:
    # {"room_type": [{"room": "NICU", "per_day_rent": 15000}], "icu": 3000, "ot_charge": 3000}
    room_charges = Column(JSONB, nullable=True)
    # Raw AI-extracted MOU payload kept for audit / re-edit.
    extracted_data = Column(JSONB, nullable=True)
    mou_original_filename = Column(String, nullable=True)
    mou_stored_filename = Column(String, nullable=True)
    mou_file_path = Column(String, nullable=True)
    mou_content_type = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
