from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.email import SendEmailResponse, InboxEmailResponse
from app.controllers import email_controller

router = APIRouter(prefix="/email", tags=["Email"])


@router.post("/send", response_model=SendEmailResponse)
async def send_form_email(
    claim_case_id: UUID = Form(...),
    to_email: str = Form(...),
    subject: str = Form(...),
    content: str = Form(...),
    cc_emails: list[str] = Form(default=[]),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pdf_data = await file.read() if file else None
    return email_controller.send_form_email(
        db=db,
        claim_case_id=claim_case_id,
        to_email=to_email,
        subject=subject,
        content=content,
        cc_emails=cc_emails,
        pdf_data=pdf_data,
        pdf_filename=file.filename or "form.pdf" if file else "form.pdf",
    )


@router.post("/query", response_model=SendEmailResponse)
async def send_query_email(
    claim_case_id: UUID = Form(...),
    to_email: str = Form(...),
    subject: str = Form(...),
    content: str = Form(...),
    cc_emails: list[str] = Form(default=[]),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pdf_data = await file.read() if file else None
    return email_controller.send_query_email(
        db=db,
        claim_case_id=claim_case_id,
        to_email=to_email,
        subject=subject,
        content=content,
        cc_emails=cc_emails,
        pdf_data=pdf_data,
        pdf_filename=file.filename or "form.pdf" if file else "form.pdf",
    )


@router.get("/inbox", response_model=list[InboxEmailResponse])
def get_inbox(
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    return email_controller.get_inbox(limit)
