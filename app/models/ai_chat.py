import uuid

from sqlalchemy import Column, String, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class AiChat(Base):
    """One AI-assistant conversation, private to a single user."""

    __tablename__ = "ai_chat"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=False)
    title = Column(String, nullable=False, default="New chat")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    messages = relationship(
        "AiChatMessage",
        back_populates="chat",
        cascade="all, delete-orphan",
        order_by="AiChatMessage.id",
    )

    __table_args__ = (
        Index("ix_ai_chat_user_id", "user_id"),
    )
