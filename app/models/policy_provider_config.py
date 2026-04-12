import uuid

from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class PolicyProviderConfig(Base):
    __tablename__ = "policy_provider_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    tpa_name = Column(String, nullable=True)
    tpa_toll_free_phone = Column(String, nullable=True)
    tpa_toll_free_fax = Column(String, nullable=True)
    config = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
