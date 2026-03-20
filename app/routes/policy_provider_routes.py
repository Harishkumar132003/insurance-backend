from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_super_admin
from app.models.user import User
from app.schemas.policy_provider_config import PolicyProviderCreate, PolicyProviderUpdate, PolicyProviderResponse
from app.schemas.workflow import WorkflowRunRequest, WorkflowRunResponse, PolicyWorkflowRunResponse
from app.controllers import policy_provider_config_controller
from app.services.workflow_executor import execute_workflow_from_config

router = APIRouter(tags=["Policy Providers"])


@router.post("/policy-providers", response_model=PolicyProviderResponse, status_code=201)
def create_provider(
    payload: PolicyProviderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    return policy_provider_config_controller.create_provider(db, payload)


@router.get("/policy-providers", response_model=list[PolicyProviderResponse])
def list_providers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return policy_provider_config_controller.get_all_providers(db)


@router.get("/policy-providers/{provider_id}", response_model=PolicyProviderResponse)
def get_provider(
    provider_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return policy_provider_config_controller.get_provider(db, provider_id)


@router.put("/policy-providers/{provider_id}", response_model=PolicyProviderResponse)
def update_provider(
    provider_id: UUID,
    payload: PolicyProviderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    return policy_provider_config_controller.update_provider(db, provider_id, payload)


@router.delete("/policy-providers/{provider_id}")
def delete_provider(
    provider_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    return policy_provider_config_controller.delete_provider(db, provider_id)


@router.post("/run-policy/{provider_id}/{policy_id}", response_model=PolicyWorkflowRunResponse)
async def run_policy_workflow(
    provider_id: str,
    policy_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    provider = policy_provider_config_controller.get_provider_by_provider_id(db, provider_id)
    return await execute_workflow_from_config(provider.config, {"policy_id": policy_id})
