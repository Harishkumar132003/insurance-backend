"""Public (unauthenticated) intent-detection route.

POST /api/v1/ai/intent — takes a natural-language query and returns a structured,
cube-aligned intent. Intent-only: no data is queried or returned. Unauthenticated
by design (returns a parsed intent, not any tenant data).
"""
from fastapi import APIRouter

from app.controllers import intent_controller
from app.schemas.intent import IntentRequest
from app.schemas.nl_sql import NlSqlResponse

router = APIRouter(prefix="/ai", tags=["AI Intent (public)"])


@router.post("/intent", response_model=NlSqlResponse)
async def detect_intent(payload: IntentRequest):
    """NL query -> classify (normal/not_permitted/db_query) -> concepts ->
    vector retrieval -> Cube SQL -> execute -> human answer. Returns the kind,
    concepts, the executed SQL, result rows, and the answer."""
    return await intent_controller.detect(payload)
