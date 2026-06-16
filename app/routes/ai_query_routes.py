import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.controllers import ai_query_controller, ai_chat_controller
from app.core.deps import require_hospital_admin
from app.db.session import get_db
from app.models.user import User
from app.services import ai_query_service
from app.schemas.ai_query import (
    AiChatDetailResponse,
    AiChatListItem,
    AiChatMessageResponse,
    AiChatRenameRequest,
    AiQueryRequest,
    AiQueryResponse,
)

router = APIRouter(prefix="/ai", tags=["AI Assistant"])

# Headers that keep SSE flowing through proxies (nginx buffering off, no caching).
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event_iter):
    """Wrap an iterator of {"event", "data"} dicts as a text/event-stream body."""
    async def gen():
        async for ev in event_iter:
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], default=str)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/query", response_model=AiQueryResponse)
async def ai_query(
    payload: AiQueryRequest,
    current_user: User = Depends(require_hospital_admin),
):
    """One-shot question (no persistence). Kept for compatibility; the chat
    endpoints below are what the UI uses."""
    return await ai_query_controller.ask(current_user, payload)


@router.post("/query/stream")
async def ai_query_stream(
    payload: AiQueryRequest,
    current_user: User = Depends(require_hospital_admin),
):
    """One-shot question over SSE (no persistence). Emits status/plan/step events
    and a final `done` event — avoids request timeouts on long agent runs."""
    if not current_user.hospital_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This assistant is available to hospital users only.",
        )
    return _sse(ai_query_service.astream_answer(
        str(current_user.hospital_id), payload.question,
    ))


# ---- Persistent per-user chats ---------------------------------------------
@router.get("/chats", response_model=list[AiChatListItem])
def list_chats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    return ai_chat_controller.list_chats(db, current_user)


@router.post("/chats", response_model=AiChatDetailResponse, status_code=201)
def create_chat(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    return ai_chat_controller.create_chat(db, current_user)


@router.get("/chats/{chat_id}", response_model=AiChatDetailResponse)
def get_chat(
    chat_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    return ai_chat_controller.get_chat(db, current_user, chat_id)


@router.post("/chats/{chat_id}/messages", response_model=AiChatMessageResponse)
async def send_message(
    chat_id: UUID,
    payload: AiQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    """Send a question to a chat: stores it, runs the agent with the chat's
    recent context, stores + returns the assistant's answer."""
    return await ai_chat_controller.send_message(db, current_user, chat_id, payload.question)


@router.post("/chats/{chat_id}/messages/stream")
async def send_message_stream(
    chat_id: UUID,
    payload: AiQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    """Same as send_message, but streamed over SSE so long agent runs don't time
    out. The user message is persisted up front; the assistant message is saved
    when the final `done` event fires (which also carries the saved row id)."""
    hospital_id, history = ai_chat_controller.prepare_message(
        db, current_user, chat_id, payload.question,
    )
    return _sse(ai_chat_controller.stream_message(
        chat_id, hospital_id, payload.question, history,
    ))


@router.patch("/chats/{chat_id}", response_model=AiChatListItem)
def rename_chat(
    chat_id: UUID,
    payload: AiChatRenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    return ai_chat_controller.rename_chat(db, current_user, chat_id, payload.title)


@router.delete("/chats/{chat_id}", status_code=204)
def delete_chat(
    chat_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    ai_chat_controller.delete_chat(db, current_user, chat_id)
