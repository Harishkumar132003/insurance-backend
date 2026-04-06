from sqlalchemy import Column, BigInteger, String, Text, Boolean, DateTime, func

from app.db.base import Base


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
