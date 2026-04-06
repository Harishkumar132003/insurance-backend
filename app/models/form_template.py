from sqlalchemy import Column, BigInteger, String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class FormTemplate(Base):
    __tablename__ = "form_templates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    schema_json = Column(JSONB, nullable=False)
    policy_provider_id = Column(UUID(as_uuid=True), ForeignKey("policy_provider_configs.id"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_form_template_name_version"),
    )
