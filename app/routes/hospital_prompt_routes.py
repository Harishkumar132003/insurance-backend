from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_super_admin
from app.models.user import User
from app.schemas.hospital_prompt import HospitalPromptCreate, HospitalPromptUpdate, HospitalPromptResponse
from app.controllers import hospital_prompt_controller

router = APIRouter(prefix="/hospitals", tags=["Hospital Prompts"])


@router.post("/{hospital_id}/prompts", response_model=HospitalPromptResponse, status_code=201)
def create_prompt(
    hospital_id: UUID,
    payload: HospitalPromptCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    return hospital_prompt_controller.create_prompt(db, hospital_id, payload, current_user)


@router.get("/{hospital_id}/prompts", response_model=list[HospitalPromptResponse])
def list_prompts(
    hospital_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return hospital_prompt_controller.get_all_prompts(db, hospital_id, current_user)


@router.get("/{hospital_id}/prompts/{prompt_id}", response_model=HospitalPromptResponse)
def get_prompt(
    hospital_id: UUID,
    prompt_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return hospital_prompt_controller.get_prompt(db, hospital_id, prompt_id, current_user)


@router.put("/{hospital_id}/prompts/{prompt_id}", response_model=HospitalPromptResponse)
def update_prompt(
    hospital_id: UUID,
    prompt_id: UUID,
    payload: HospitalPromptUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    return hospital_prompt_controller.update_prompt(db, hospital_id, prompt_id, payload, current_user)


@router.delete("/{hospital_id}/prompts/{prompt_id}")
def delete_prompt(
    hospital_id: UUID,
    prompt_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    return hospital_prompt_controller.delete_prompt(db, hospital_id, prompt_id, current_user)
