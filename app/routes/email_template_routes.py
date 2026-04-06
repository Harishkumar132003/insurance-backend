from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.email_template import EmailTemplateCreate, EmailTemplateResponse
from app.controllers import email_template_controller

router = APIRouter(prefix="/email-templates", tags=["Email Templates"])


@router.post("", response_model=EmailTemplateResponse, status_code=201)
def create_email_template(
    payload: EmailTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return email_template_controller.create_email_template(db, payload)


@router.get("", response_model=list[EmailTemplateResponse])
def get_all_email_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return email_template_controller.get_all_email_templates(db)


@router.get("/{template_id}", response_model=EmailTemplateResponse)
def get_email_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return email_template_controller.get_email_template(db, template_id)
