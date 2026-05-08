import json
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, File, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.email import SendEmailResponse, InboxEmailResponse
from app.controllers import email_controller

router = APIRouter(prefix="/email", tags=["Email"])


def _parse_form_values(raw: str | None) -> dict | None:
    if raw is None or raw == "":
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"form_values is not valid JSON: {e}",
        )
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="form_values must be a JSON object",
        )
    return parsed


@router.post("/send", response_model=SendEmailResponse)
async def send_form_email(
    claim_case_id: UUID = Form(...),
    to_email: str = Form(...),
    subject: str = Form(...),
    content: str = Form(...),
    cc_emails: list[str] = Form(default=[]),
    form_values: str | None = Form(default=None),
    email_type: str | None = Form(default=None),
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
        form_values=_parse_form_values(form_values),
        email_type=email_type,
    )


@router.post("/query", response_model=SendEmailResponse)
async def send_query_email(
    claim_case_id: UUID = Form(...),
    to_email: str = Form(...),
    subject: str = Form(...),
    content: str = Form(...),
    cc_emails: list[str] = Form(default=[]),
    form_values: str | None = Form(default=None),
    email_type: str | None = Form(default=None),
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
        form_values=_parse_form_values(form_values),
        email_type=email_type,
    )


@router.get("/inbox", response_model=list[InboxEmailResponse])
def get_inbox(
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    return email_controller.get_inbox(limit)
