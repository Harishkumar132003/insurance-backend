import uuid

from sqlalchemy import Column, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=False)
    config_id = Column(UUID(as_uuid=True), ForeignKey("hospital_configs.id"), nullable=False)
    status = Column(String, nullable=False)  # e.g. "success", "failure"
    request_data = Column(JSONB, nullable=True)
    response_data = Column(JSONB, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
