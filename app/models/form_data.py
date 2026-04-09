from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


class FormData(Base):
    __tablename__ = "form_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(UUID(as_uuid=True), ForeignKey("claim_cases.id"), nullable=True)
    data_json = Column(JSONB, nullable=False)
    status = Column(String, nullable=False, default="DRAFT")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    claim_case = relationship("ClaimCase", back_populates="form_data")
