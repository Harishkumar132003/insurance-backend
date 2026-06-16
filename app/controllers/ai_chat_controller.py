"""Per-user AI assistant chats: CRUD + sending a message (runs the agent)."""

import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.ai_chat import AiChat
from app.models.ai_chat_message import AiChatMessage
from app.models.user import User
from app.schemas.ai_query import (
    AiChatDetailResponse,
    AiChatListItem,
    AiChatMessageResponse,
)
from app.services import ai_query_service

logger = logging.getLogger(__name__)

HISTORY_TURNS = 4  # prior messages passed to the agent for context


def _require_hospital(user: User) -> UUID:
    if not user.hospital_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This assistant is available to hospital users only.",
        )
    return user.hospital_id


def _msg_to_response(m: AiChatMessage, plan: dict | None = None) -> AiChatMessageResponse:
    return AiChatMessageResponse(
        id=m.id,
        role=m.role,
        content=m.content or "",
        sql=m.sql or [],
        columns=m.columns or [],
        rows=m.rows or [],
        created_at=m.created_at,
        plan=plan,  # transient — populated on a fresh send, not from storage
    )


def list_chats(db: Session, user: User) -> list[AiChatListItem]:
    chats = (
        db.query(AiChat)
        .filter(AiChat.user_id == user.id)
        .order_by(AiChat.updated_at.desc())
        .all()
    )
    return [AiChatListItem(id=c.id, title=c.title, updated_at=c.updated_at) for c in chats]


def create_chat(db: Session, user: User) -> AiChatDetailResponse:
    _require_hospital(user)
    chat = AiChat(user_id=user.id, hospital_id=user.hospital_id, title="New chat")
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return AiChatDetailResponse(id=chat.id, title=chat.title, messages=[])


def _get_owned(db: Session, user: User, chat_id: UUID) -> AiChat:
    chat = (
        db.query(AiChat)
        .filter(AiChat.id == chat_id, AiChat.user_id == user.id)
        .first()
    )
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found.")
    return chat


def get_chat(db: Session, user: User, chat_id: UUID) -> AiChatDetailResponse:
    chat = _get_owned(db, user, chat_id)
    return AiChatDetailResponse(
        id=chat.id,
        title=chat.title,
        messages=[_msg_to_response(m) for m in chat.messages],
    )


def rename_chat(db: Session, user: User, chat_id: UUID, title: str) -> AiChatListItem:
    chat = _get_owned(db, user, chat_id)
    chat.title = title.strip()[:200] or chat.title
    db.commit()
    db.refresh(chat)
    return AiChatListItem(id=chat.id, title=chat.title, updated_at=chat.updated_at)


def delete_chat(db: Session, user: User, chat_id: UUID) -> None:
    chat = _get_owned(db, user, chat_id)
    db.delete(chat)
    db.commit()


async def send_message(db: Session, user: User, chat_id: UUID, question: str) -> AiChatMessageResponse:
    hospital_id = _require_hospital(user)
    chat = _get_owned(db, user, chat_id)

    # Last few turns as context for follow-up questions.
    prior = chat.messages[-HISTORY_TURNS:]
    history = [{"role": m.role, "content": m.content or ""} for m in prior]

    # Persist the user's message.
    chat.messages.append(AiChatMessage(role="user", content=question))

    try:
        result = await ai_query_service.answer_question(
            hospital_id=str(hospital_id), question=question, history=history,
        )
    except RuntimeError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except Exception:
        db.rollback()
        logger.exception("AI chat message failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant couldn't answer that. Please rephrase and try again.",
        )

    assistant = AiChatMessage(
        role="assistant",
        content=result["answer"],
        sql=result["sql"],
        columns=result["columns"],
        rows=result["rows"],
    )
    chat.messages.append(assistant)

    # First exchange names the chat from the question.
    if chat.title == "New chat":
        chat.title = (question.strip()[:60] + ("…" if len(question.strip()) > 60 else "")) or "New chat"

    db.commit()
    db.refresh(assistant)
    return _msg_to_response(assistant, plan=result.get("plan"))


def prepare_message(db: Session, user: User, chat_id: UUID, question: str):
    """Validate access and persist the user's message before streaming begins.
    Raising here yields a clean HTTP error (404/400), not a mid-stream failure.
    Returns (hospital_id, history)."""
    hospital_id = _require_hospital(user)
    chat = _get_owned(db, user, chat_id)

    prior = chat.messages[-HISTORY_TURNS:]
    history = [{"role": m.role, "content": m.content or ""} for m in prior]

    chat.messages.append(AiChatMessage(role="user", content=question))
    if chat.title == "New chat":
        chat.title = (question.strip()[:60] + ("…" if len(question.strip()) > 60 else "")) or "New chat"
    db.commit()
    return hospital_id, history


async def stream_message(chat_id: UUID, hospital_id, question: str, history: list[dict]):
    """SSE generator: stream the agent's progress, persist the assistant message
    when the final `done` event arrives, and enrich it with the saved row id.

    Uses its OWN short-lived session (opened only at persist time): the request's
    `Depends(get_db)` session is closed before this generator finishes streaming,
    so the request-scoped objects are detached by the time `done` arrives.
    """
    try:
        async for ev in ai_query_service.astream_answer(str(hospital_id), question, history):
            if ev["event"] == "done":
                d = ev["data"]
                db = SessionLocal()
                try:
                    assistant = AiChatMessage(
                        chat_id=chat_id,           # insert by FK; no relationship/lazy-load
                        role="assistant",
                        content=d.get("answer", ""),
                        sql=d.get("sql", []),
                        columns=d.get("columns", []),
                        rows=d.get("rows", []),
                    )
                    db.add(assistant)
                    db.commit()
                    db.refresh(assistant)
                    d["id"] = assistant.id
                    d["created_at"] = assistant.created_at.isoformat() if assistant.created_at else None
                finally:
                    db.close()
            yield ev
    except Exception:  # noqa: BLE001 — surface as an SSE error, not a 500
        logger.exception("AI chat stream failed")
        yield {"event": "error",
               "data": {"detail": "The assistant couldn't answer that. Please try again."}}
