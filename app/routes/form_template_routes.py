from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.form_template import FormTemplateCreate, FormTemplateResponse, FormTemplateWithProviderResponse
from app.controllers import form_template_controller

router = APIRouter(prefix="/form-templates", tags=["Form Templates"])


@router.post("", response_model=FormTemplateResponse, status_code=201)
def create_form_template(
    payload: FormTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return form_template_controller.create_form_template(db, payload)


@router.get("", response_model=list[FormTemplateWithProviderResponse])
def list_form_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return form_template_controller.get_all_form_templates(db)


@router.get("/{template_id}", response_model=FormTemplateResponse)
def get_form_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return form_template_controller.get_form_template_by_id(db, template_id)


@router.get("/first", response_model=FormTemplateResponse)
def get_first_form_template(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return form_template_controller.get_first_form_template(db)


@router.get("/provider/{policy_provider_id}", response_model=FormTemplateResponse)
def get_form_template_by_provider(
    policy_provider_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return form_template_controller.get_form_template_by_provider(db, policy_provider_id)
