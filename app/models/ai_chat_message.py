from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


class AiChatMessage(Base):
    """One message in an AI chat. Assistant rows also carry the SQL/columns/rows
    the agent produced so the UI can re-render the result table + 'Show SQL'."""

    __tablename__ = "ai_chat_message"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ai_chat.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String, nullable=False)  # 'user' | 'assistant'
    content = Column(Text, nullable=False, default="")
    sql = Column(JSONB, nullable=True)       # list[str]
    columns = Column(JSONB, nullable=True)   # list[str]
    rows = Column(JSONB, nullable=True)      # list[dict]
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chat = relationship("AiChat", back_populates="messages")

    __table_args__ = (
        Index("ix_ai_chat_message_chat_id", "chat_id"),
    )
