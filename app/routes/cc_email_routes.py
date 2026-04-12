from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.cc_email import CcEmailCreate, CcEmailUpdate, CcEmailResponse
from app.controllers import cc_email_controller

router = APIRouter(tags=["CC Emails"])


@router.post("/cc-emails", response_model=CcEmailResponse, status_code=201)
def create_cc_email(
    payload: CcEmailCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return cc_email_controller.create_cc_email(db, payload)


@router.get("/hospitals/{hospital_id}/cc-emails", response_model=list[CcEmailResponse])
def list_hospital_cc_emails(
    hospital_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return cc_email_controller.list_cc_emails_for_hospital(db, hospital_id)


@router.get("/policy-providers/{provider_id}/cc-emails", response_model=list[CcEmailResponse])
def list_provider_cc_emails(
    provider_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return cc_email_controller.list_cc_emails_for_provider(db, provider_id)


@router.put("/cc-emails/{cc_email_id}", response_model=CcEmailResponse)
def update_cc_email(
    cc_email_id: int,
    payload: CcEmailUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return cc_email_controller.update_cc_email(db, cc_email_id, payload)


@router.delete("/cc-emails/{cc_email_id}")
def delete_cc_email(
    cc_email_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return cc_email_controller.delete_cc_email(db, cc_email_id)
