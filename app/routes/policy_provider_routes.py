from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_super_admin
from app.models.user import User
from app.schemas.policy_provider_config import PolicyProviderCreate, PolicyProviderUpdate, PolicyProviderResponse
from app.schemas.workflow import PolicyWorkflowRunResponse
from app.controllers import policy_provider_config_controller
from app.services.workflow_executor import execute_policy_workflow_with_summary

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


@router.post("/run-policy/{provider_id}", response_model=PolicyWorkflowRunResponse)
@router.post("/run-policy/{provider_id}/{policy_id}", response_model=PolicyWorkflowRunResponse)
async def run_policy_workflow(
    provider_id: str,
    request: Request,
    policy_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uploaded_file = None
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        uploaded_file = form.get("file")

    file_name: str | None = None
    file_content_type: str | None = None
    file_bytes: bytes | None = None

    if uploaded_file is not None and hasattr(uploaded_file, "read"):
        file_name = getattr(uploaded_file, "filename", None)
        file_content_type = getattr(uploaded_file, "content_type", None)
        file_bytes = await uploaded_file.read()

    provider = policy_provider_config_controller.get_provider_by_provider_id(db, provider_id)
    input_data = {"policy_id": policy_id} if policy_id else {}
    return await execute_policy_workflow_with_summary(
        db,
        provider.config,
        input_data,
        file_name=file_name,
        file_content_type=file_content_type,
        file_bytes=file_bytes,
    )
