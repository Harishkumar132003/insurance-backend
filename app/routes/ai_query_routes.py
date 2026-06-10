from fastapi import APIRouter, Depends

from app.controllers import ai_query_controller
from app.core.deps import require_hospital_admin
from app.models.user import User
from app.schemas.ai_query import AiQueryRequest, AiQueryResponse

router = APIRouter(prefix="/ai", tags=["AI Assistant"])


@router.post("/query", response_model=AiQueryResponse)
async def ai_query(
    payload: AiQueryRequest,
    current_user: User = Depends(require_hospital_admin),
):
    """Answer a natural-language question about this hospital's data.

    The query is executed by a read-only, RLS-scoped database agent — results
    are always limited to the caller's own hospital.
    """
    return await ai_query_controller.ask(current_user, payload)
