from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.workflow import WorkflowRunRequest, WorkflowRunResponse
from app.services.workflow_executor import execute_workflow

router = APIRouter(tags=["Workflow"])


@router.post("/run/{hospital_id}", response_model=WorkflowRunResponse)
async def run_workflow(
    hospital_id: UUID,
    payload: WorkflowRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await execute_workflow(db, hospital_id, payload.input)
