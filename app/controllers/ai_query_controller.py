"""Controller for the hospital-admin AI query assistant."""

import logging

from fastapi import HTTPException, status

from app.models.user import User
from app.schemas.ai_query import AiQueryRequest, AiQueryResponse
from app.services import ai_query_service

logger = logging.getLogger(__name__)


async def ask(current_user: User, payload: AiQueryRequest) -> AiQueryResponse:
    # The agent is hard-scoped to one hospital via RLS; a user without a
    # hospital (e.g. a super admin) has no tenant to scope to.
    if not current_user.hospital_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This assistant is available to hospital users only.",
        )

    try:
        result = await ai_query_service.answer_question(
            hospital_id=str(current_user.hospital_id),
            question=payload.question,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:  # noqa: BLE001 — don't leak internals to the client
        logger.exception("AI query failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant couldn't answer that. Please rephrase and try again.",
        )

    return AiQueryResponse(**result)
