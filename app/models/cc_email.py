from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class CcEmail(Base):
    __tablename__ = "cc_emails"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    email = Column(String, nullable=False)
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=True)
    policy_provider_id = Column(UUID(as_uuid=True), ForeignKey("policy_provider_configs.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
