import math
from datetime import datetime, timezone

from fastapi import HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.claim_case import ClaimCase
from app.models.claim_case_email import ClaimCaseEmail
from app.models.claim_case_email_attachment import ClaimCaseEmailAttachment
from app.models.query_log import QueryLog
from app.models.status_history import StatusHistory
from app.utils.file_storage import get_attachment_full_path


def get_all_claim_case_emails(db: Session, hospital_id, page: int = 1, page_size: int = 20, claim_case_id=None) -> dict:
    # Subquery: latest email id per claim_case
    latest_subq_query = (
        db.query(func.max(ClaimCaseEmail.id).label("max_id"))
        .join(ClaimCase, ClaimCaseEmail.claim_case_id == ClaimCase.id)
        .filter(ClaimCase.hospital_id == hospital_id)
    )
    if claim_case_id:
        latest_subq_query = latest_subq_query.filter(ClaimCaseEmail.claim_case_id == claim_case_id)
    latest_subq = latest_subq_query.group_by(ClaimCaseEmail.claim_case_id).subquery()

    base_query = (
        db.query(ClaimCaseEmail, ClaimCase.claim_number)
        .join(ClaimCase, ClaimCaseEmail.claim_case_id == ClaimCase.id)
        .filter(ClaimCase.hospital_id == hospital_id)
    )
    if claim_case_id:
        base_query = base_query.filter(ClaimCaseEmail.claim_case_id == claim_case_id)

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

    # Collect latest email ids
    latest_ids = {row.max_id for row in db.query(latest_subq.c.max_id).all()}

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
            "is_read": email.is_read,
            "ai_suggested_status": email.ai_suggested_status,
            "validation_status": email.validation_status,
            "is_latest": email.id in latest_ids,
            "created_at": email.created_at,
            "attachment_count": len(email.attachments),
            "attachments": [
                {
                    "id": att.id,
                    "original_filename": att.original_filename,
                    "content_type": att.content_type,
                    "file_size": att.file_size,
                    "created_at": att.created_at,
                }
                for att in email.attachments
            ],
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
            "is_read": e.is_read,
            "ai_suggested_status": e.ai_suggested_status,
            "validation_status": e.validation_status,
            "created_at": e.created_at,
            "attachment_count": len(e.attachments),
        })
    return result


def get_all_emails_with_attachments(db: Session, claim_case_id, is_read: bool | None = None):
    query = (
        db.query(ClaimCaseEmail)
        .options(joinedload(ClaimCaseEmail.attachments))
        .filter(ClaimCaseEmail.claim_case_id == claim_case_id)
    )
    if is_read is not None:
        query = query.filter(ClaimCaseEmail.is_read == is_read)
    emails = (
        query.order_by(ClaimCaseEmail.created_at.asc())
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


def mark_email_as_read(db: Session, claim_case_id, email_id: int):
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

    email.is_read = True
    db.commit()
    db.refresh(email)
    return email


def validate_email_suggestion(
    db: Session, claim_case_id, email_id: int,
    validation_status: str, user_id, remarks: str | None = None,
):
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

    if not email.is_read:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email must be read before validation",
        )

    if email.ai_suggested_status is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No AI suggestion to validate",
        )

    if email.validation_status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already validated",
        )

    if validation_status not in ("APPROVED", "REJECTED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="validation_status must be APPROVED or REJECTED",
        )

    email.validation_status = validation_status
    email.validated_at = datetime.now(timezone.utc)
    email.validated_by = user_id

    if validation_status == "APPROVED":
        claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
        if not claim_case:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Claim case not found"
            )

        # Apply AI suggestion to claim case. The provider's reply moves the
        # workflow back into the matching outcome state in the flow diagram.
        claim_case.claim_status = email.ai_suggested_status
        claim_case.status = email.ai_suggested_status

        if email.ai_suggested_claim_number and not claim_case.claim_number:
            claim_case.claim_number = email.ai_suggested_claim_number

        if (
            email.ai_suggested_status in ("APPROVED", "PARTIALLY_APPROVED")
            and email.ai_suggested_amount is not None
        ):
            claim_case.approved_amount = float(email.ai_suggested_amount)

        # Create QueryLog when provider asks for docs / clarification
        if email.ai_suggested_status == "ADR_NMI":
            db.add(QueryLog(
                claim_case_id=claim_case.id,
                query_type=email.ai_suggested_status,
                query_details=email.ai_query_details or email.ai_summary,
                documents_requested=email.ai_documents_requested,
                status="OPEN",
            ))

        # Resolve open QueryLogs on a terminal outcome
        if email.ai_suggested_status in ("APPROVED", "PARTIALLY_APPROVED", "DENIED"):
            open_queries = (
                db.query(QueryLog)
                .filter(QueryLog.claim_case_id == claim_case.id, QueryLog.status == "OPEN")
                .all()
            )
            for q in open_queries:
                q.status = "RESOLVED"
                q.resolved_at = datetime.now(timezone.utc)

        # Create StatusHistory
        db.add(StatusHistory(
            claim_case_id=claim_case.id,
            stage=claim_case.current_stage,
            status=email.ai_suggested_status,
            remarks=remarks or email.ai_summary or "AI suggestion approved by user",
            changed_by="EMAIL_VALIDATED",
            updated_by=user_id,
        ))

    db.commit()
    db.refresh(email)
    return email
