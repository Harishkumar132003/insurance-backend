from sqlalchemy import Column, BigInteger, String, Integer, DateTime, func

from app.db.base import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    age = Column(Integer)
    gender = Column(String(10))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
