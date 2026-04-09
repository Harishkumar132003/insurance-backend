import math

from fastapi import HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.claim_case import ClaimCase
from app.models.claim_case_email import ClaimCaseEmail
from app.models.claim_case_email_attachment import ClaimCaseEmailAttachment
from app.utils.file_storage import get_attachment_full_path


def get_all_claim_case_emails(db: Session, hospital_id, page: int = 1, page_size: int = 20) -> dict:
    base_query = (
        db.query(ClaimCaseEmail, ClaimCase.claim_number)
        .join(ClaimCase, ClaimCaseEmail.claim_case_id == ClaimCase.id)
        .filter(ClaimCase.hospital_id == hospital_id)
    )

    total = base_query.count()
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    offset = (page - 1) * page_size

    rows = (
        base_query
        .options(joinedload(ClaimCaseEmail.attachments))
        .order_by(ClaimCaseEmail.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = []
    for email, claim_number in rows:
        items.append({
            "id": email.id,
            "claim_case_id": email.claim_case_id,
            "claim_number": claim_number,
            "direction": email.direction,
            "email_type": email.email_type,
            "from_email": email.from_email,
            "to_email": email.to_email,
            "subject": email.subject,
            "email_date": email.email_date,
            "created_at": email.created_at,
            "attachment_count": len(email.attachments),
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def get_emails_for_claim_case(
    db: Session, claim_case_id, direction: str | None = None, email_type: str | None = None
) -> list[dict]:
    query = db.query(ClaimCaseEmail).filter(
        ClaimCaseEmail.claim_case_id == claim_case_id
    )
    if direction:
        query = query.filter(ClaimCaseEmail.direction == direction.upper())
    if email_type:
        query = query.filter(ClaimCaseEmail.email_type == email_type.upper())

    emails = (
        query.options(joinedload(ClaimCaseEmail.attachments))
        .order_by(ClaimCaseEmail.created_at.desc())
        .all()
    )

    result = []
    for e in emails:
        result.append({
            "id": e.id,
            "direction": e.direction,
            "email_type": e.email_type,
            "from_email": e.from_email,
            "to_email": e.to_email,
            "subject": e.subject,
            "email_date": e.email_date,
            "created_at": e.created_at,
            "attachment_count": len(e.attachments),
        })
    return result


def get_all_emails_with_attachments(db: Session, claim_case_id):
    emails = (
        db.query(ClaimCaseEmail)
        .options(joinedload(ClaimCaseEmail.attachments))
        .filter(ClaimCaseEmail.claim_case_id == claim_case_id)
        .order_by(ClaimCaseEmail.created_at.asc())
        .all()
    )
    return emails


def get_email_detail(db: Session, claim_case_id, email_id: int):
    email = (
        db.query(ClaimCaseEmail)
        .options(joinedload(ClaimCaseEmail.attachments))
        .filter(
            ClaimCaseEmail.id == email_id,
            ClaimCaseEmail.claim_case_id == claim_case_id,
        )
        .first()
    )
    if not email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Email not found"
        )
    return email


def download_attachment(
    db: Session, claim_case_id, email_id: int, attachment_id: int
):
    attachment = (
        db.query(ClaimCaseEmailAttachment)
        .filter(
            ClaimCaseEmailAttachment.id == attachment_id,
            ClaimCaseEmailAttachment.email_id == email_id,
            ClaimCaseEmailAttachment.claim_case_id == claim_case_id,
        )
        .first()
    )
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        )

    full_path = get_attachment_full_path(attachment.file_path)
    return FileResponse(
        path=full_path,
        filename=attachment.original_filename,
        media_type=attachment.content_type or "application/octet-stream",
    )


def view_attachment(
    db: Session, claim_case_id, email_id: int, attachment_id: int
):
    attachment = (
        db.query(ClaimCaseEmailAttachment)
        .filter(
            ClaimCaseEmailAttachment.id == attachment_id,
            ClaimCaseEmailAttachment.email_id == email_id,
            ClaimCaseEmailAttachment.claim_case_id == claim_case_id,
        )
        .first()
    )
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        )

    full_path = get_attachment_full_path(attachment.file_path)
    return FileResponse(
        path=full_path,
        media_type=attachment.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{attachment.original_filename}"'},
    )
