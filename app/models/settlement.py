from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class Settlement(Base):
    __tablename__ = "settlements"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_id = Column(BigInteger, ForeignKey("claims.id"), unique=True, nullable=False)
    settled_amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String, nullable=False, default="INITIATED")
    settlement_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="settlement")
