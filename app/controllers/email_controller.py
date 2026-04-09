import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.claim_case import ClaimCase
from app.models.claim_case_document import ClaimCaseDocument
from app.models.claim_case_email import ClaimCaseEmail
from app.models.claim_case_email_attachment import ClaimCaseEmailAttachment
from app.models.policy_provider_config import PolicyProviderConfig
from app.models.status_history import StatusHistory
from app.services.email_service import send_email, fetch_inbox
from app.utils.file_storage import save_attachment, read_file


def send_form_email(
    db: Session,
    claim_case_id,
    subject: str,
    content: str,
    pdf_data: bytes | None = None,
    pdf_filename: str = "form.pdf",
) -> dict:
    # 1. Fetch claim_case
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )

    # 2. Fetch provider and get email
    provider = db.query(PolicyProviderConfig).filter(
        PolicyProviderConfig.id == claim_case.policy_provider_id
    ).first()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy provider not found",
        )
    if not provider.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Policy provider does not have an email configured",
        )

    # 3. Generate thread_id if not exists and append to subject
    if not claim_case.thread_id:
        claim_case.thread_id = uuid.uuid4().hex[:12]
    subject = f"{subject} [{claim_case.thread_id}]"

    # 4. Build attachments list: form PDF + uploaded documents
    attachments: list[tuple[bytes, str, str]] = []
    if pdf_data:
        attachments.append((pdf_data, pdf_filename, "application/pdf"))

    documents = db.query(ClaimCaseDocument).filter(
        ClaimCaseDocument.claim_case_id == claim_case_id
    ).all()
    for doc in documents:
        file_bytes = read_file(doc.file_path)
        attachments.append((
            file_bytes,
            doc.original_filename,
            doc.content_type or "application/octet-stream",
        ))

    # 5. Send email with all attachments
    send_email(
        to_email=provider.email,
        subject=subject,
        body=content,
        attachments=attachments or None,
    )

    # 6. Update claim_case status to APPLIED
    claim_case.status = "APPLIED"
    db.add(StatusHistory(
        claim_case_id=claim_case.id,
        stage="PRE_AUTH",
        status="APPLIED",
        remarks=f"Email sent to {provider.email}",
    ))

    # 7. Persist the sent email record
    email_record = ClaimCaseEmail(
        claim_case_id=claim_case.id,
        direction="SENT",
        from_email=settings.EMAIL_ADDRESS,
        to_email=provider.email,
        subject=subject,
        body=content,
        thread_id=claim_case.thread_id,
        email_type="APPLIED",
        email_date=datetime.now(timezone.utc),
    )
    db.add(email_record)
    db.flush()

    # 8. Save attachment records for audit trail
    for file_bytes, filename, content_type in attachments:
        stored_filename, file_path = save_attachment(
            claim_case.id, file_bytes, filename
        )
        db.add(ClaimCaseEmailAttachment(
            email_id=email_record.id,
            claim_case_id=claim_case.id,
            original_filename=filename,
            stored_filename=stored_filename,
            file_path=file_path,
            content_type=content_type,
            file_size=len(file_bytes),
        ))

    db.commit()
    db.refresh(claim_case)

    return {
        "message": "Email sent successfully",
        "to_email": provider.email,
        "subject": subject,
        "status": claim_case.status,
    }


def send_query_email(
    db: Session,
    claim_case_id,
    subject: str,
    content: str,
    pdf_data: bytes | None = None,
    pdf_filename: str = "form.pdf",
) -> dict:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )

    if not claim_case.thread_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Claim case does not have a thread_id. Send an initial email first.",
        )

    provider = db.query(PolicyProviderConfig).filter(
        PolicyProviderConfig.id == claim_case.policy_provider_id
    ).first()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy provider not found",
        )
    if not provider.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Policy provider does not have an email configured",
        )

    subject = f"{subject} [{claim_case.thread_id}]"

    # Build attachments list: optional PDF + uploaded documents
    attachments: list[tuple[bytes, str, str]] = []
    if pdf_data:
        attachments.append((pdf_data, pdf_filename, "application/pdf"))

    documents = db.query(ClaimCaseDocument).filter(
        ClaimCaseDocument.claim_case_id == claim_case_id
    ).all()
    for doc in documents:
        file_bytes = read_file(doc.file_path)
        attachments.append((
            file_bytes,
            doc.original_filename,
            doc.content_type or "application/octet-stream",
        ))

    send_email(
        to_email=provider.email,
        subject=subject,
        body=content,
        attachments=attachments or None,
    )

    db.add(StatusHistory(
        claim_case_id=claim_case.id,
        stage=claim_case.current_stage,
        status="QUERY_RAISED",
        remarks=f"Query email sent to {provider.email}",
    ))

    email_record = ClaimCaseEmail(
        claim_case_id=claim_case.id,
        direction="SENT",
        from_email=settings.EMAIL_ADDRESS,
        to_email=provider.email,
        subject=subject,
        body=content,
        thread_id=claim_case.thread_id,
        email_type="QUERY_RAISED",
        email_date=datetime.now(timezone.utc),
    )
    db.add(email_record)
    db.flush()

    for file_bytes, filename, content_type in attachments:
        stored_filename, file_path = save_attachment(
            claim_case.id, file_bytes, filename
        )
        db.add(ClaimCaseEmailAttachment(
            email_id=email_record.id,
            claim_case_id=claim_case.id,
            original_filename=filename,
            stored_filename=stored_filename,
            file_path=file_path,
            content_type=content_type,
            file_size=len(file_bytes),
        ))

    db.commit()

    return {
        "message": "Query email sent successfully",
        "to_email": provider.email,
        "subject": subject,
        "status": claim_case.status,
    }


def get_inbox(limit: int = 10) -> list[dict]:
    return fetch_inbox(limit)
