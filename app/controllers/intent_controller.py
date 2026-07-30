"""Controller for the public /ai/intent endpoint (thin orchestration).

Runs the NL -> Cube SQL pipeline: classify -> concepts -> vector retrieval ->
Cube SQL -> execute -> human answer.
"""
from app.schemas.intent import IntentRequest
from app.schemas.nl_sql import NlSqlResponse
from app.services import nl_sql_service


async def detect(payload: IntentRequest) -> NlSqlResponse:
    result = await nl_sql_service.answer_public(payload.query)
    return NlSqlResponse(**result)
