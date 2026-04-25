import uuid

from sqlalchemy import Column, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # SUPER_ADMIN, HOSPITAL_ADMIN, or INSURANCE_PROVIDER
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=True)
    policy_provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("policy_provider_configs.id"),
        nullable=True,
    )
    # NULL  -> full access (all features in app.core.features.FEATURE_KEYS)
    # []    -> no tabs
    # [...] -> only the listed feature keys
    access = Column(ARRAY(String), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    hospital = relationship("Hospital", back_populates="users")
    policy_provider = relationship("PolicyProviderConfig")
