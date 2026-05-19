"""Server-Sent Events stream for real-time notifications.

The browser's native EventSource API doesn't support custom headers, so this
endpoint accepts the JWT via `?token=...` query param rather than the usual
`Authorization: Bearer` flow used everywhere else. Existing endpoints are
untouched — only this one new entry point introduces the alternate auth path.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services.event_hub import event_hub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


# Heartbeat interval — keeps proxies from idling the connection out.
_HEARTBEAT_SECONDS = 25


def _user_from_token_query(
    token: str = Query(..., description="JWT access token"),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@router.get("/stream")
async def event_stream(
    request: Request,
    current_user: User = Depends(_user_from_token_query),
):
    if current_user.role != "HOSPITAL_ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hospital admin only")
    if current_user.hospital_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has no hospital scope")

    hospital_id = current_user.hospital_id

    async def event_generator():
        queue = await event_hub.subscribe(hospital_id)
        try:
            # Initial hello so the client knows the stream is live; useful
            # for the frontend to set its "connected" state.
            yield {"event": "ready", "data": json.dumps({"hospital_id": str(hospital_id)})}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # Heartbeat as an SSE comment line so proxies don't
                    # idle the connection out.
                    yield {"event": "ping", "data": "1"}
                    continue
                yield {
                    "event": event.get("type", "message"),
                    "data": json.dumps(event),
                }
        finally:
            await event_hub.unsubscribe(hospital_id, queue)

    return EventSourceResponse(event_generator())
