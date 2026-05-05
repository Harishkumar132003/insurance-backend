import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.core.secrets import decrypt_hospital_password
from app.models.claim_case import ClaimCase
from app.models.claim_case_document import ClaimCaseDocument
from app.models.claim_case_email import ClaimCaseEmail
from app.models.claim_case_email_attachment import ClaimCaseEmailAttachment
from app.models.hospital import Hospital
from app.models.policy_provider_config import PolicyProviderConfig
from app.models.status_history import StatusHistory
from app.controllers.claim_case_controller import QUERY_RAISE_STATE
from app.services.email_service import send_email, fetch_inbox
from app.utils.file_storage import save_attachment, read_file


def _resolve_hospital_credentials(db: Session, claim_case: ClaimCase) -> tuple[str, str]:
    """Return (email, plaintext_app_password) for the claim case's hospital."""
    if not claim_case.hospital_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Claim case has no hospital assigned",
        )
    hospital = db.query(Hospital).filter(Hospital.id == claim_case.hospital_id).first()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hospital not found"
        )
    if not hospital.email or not hospital.app_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hospital email or app_password is not configured",
        )
    password = decrypt_hospital_password(hospital.app_password, hospital.rohini_id or "")
    return hospital.email, password


def send_form_email(
    db: Session,
    claim_case_id,
    to_email: str,
    subject: str,
    content: str,
    cc_emails: list[str] | None = None,
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

    provider = (
        db.query(PolicyProviderConfig)
        .filter(PolicyProviderConfig.id == claim_case.policy_provider_id)
        .first()
    )
    is_onboarded = bool(provider and provider.is_onboarded)

    # 2. Generate thread_id if not exists and append to subject
    if not claim_case.thread_id:
        claim_case.thread_id = uuid.uuid4().hex[:12]
    subject = f"{subject} [{claim_case.thread_id}]"

    # 3. Build attachments list: form PDF + uploaded documents
    attachments: list[tuple[bytes, str, str]] = []
    if pdf_data:
        attachments.append((pdf_data, pdf_filename, "application/pdf"))

    documents = db.query(ClaimCaseDocument).filter(
        ClaimCaseDocument.claim_case_id == claim_case_id
    ).all()
    for doc in documents:
        try:
            file_bytes = read_file(doc.file_path)
        except FileNotFoundError:
            logger.warning(
                "Skipping missing attachment for claim_case=%s doc_id=%s path=%s",
                claim_case_id, doc.id, doc.file_path,
            )
            continue
        attachments.append((
            file_bytes,
            doc.original_filename,
            doc.content_type or "application/octet-stream",
        ))

    # 4. Send email from the hospital's own mailbox, or skip SMTP for onboarded
    # providers who will review the claim inside OASYS.
    if is_onboarded:
        hospital = (
            db.query(Hospital)
            .filter(Hospital.id == claim_case.hospital_id)
            .first()
            if claim_case.hospital_id else None
        )
        from_email = hospital.email if hospital and hospital.email else "onboarded@oasys.local"
    else:
        from_email, from_password = _resolve_hospital_credentials(db, claim_case)
        send_email(
            from_email=from_email,
            from_password=from_password,
            to_email=to_email,
            subject=subject,
            body=content,
            attachments=attachments or None,
            cc_emails=cc_emails or None,
        )

    # 5. Update claim_case status to SUBMITTED (initial entry into provider review)
    claim_case.status = "SUBMITTED"
    db.add(StatusHistory(
        claim_case_id=claim_case.id,
        stage="PRE_AUTH",
        status="SUBMITTED",
        remarks=(
            "Submitted to onboarded provider"
            if is_onboarded
            else f"Email sent to {to_email}"
        ),
    ))

    # 6. Persist the sent email record
    email_record = ClaimCaseEmail(
        claim_case_id=claim_case.id,
        direction="SENT",
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body=content,
        thread_id=claim_case.thread_id,
        email_type="SUBMITTED",
        email_date=datetime.now(timezone.utc),
        is_read=True,
        provider_read=not is_onboarded,
    )
    db.add(email_record)
    db.flush()

    # 7. Save attachment records for audit trail
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
        "to_email": to_email,
        "subject": subject,
        "status": claim_case.status,
    }


def send_query_email(
    db: Session,
    claim_case_id,
    to_email: str,
    subject: str,
    content: str,
    cc_emails: list[str] | None = None,
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

    provider = (
        db.query(PolicyProviderConfig)
        .filter(PolicyProviderConfig.id == claim_case.policy_provider_id)
        .first()
    )
    is_onboarded = bool(provider and provider.is_onboarded)

    subject = f"{subject} [{claim_case.thread_id}]"

    # Build attachments list: optional PDF + uploaded documents
    attachments: list[tuple[bytes, str, str]] = []
    if pdf_data:
        attachments.append((pdf_data, pdf_filename, "application/pdf"))

    documents = db.query(ClaimCaseDocument).filter(
        ClaimCaseDocument.claim_case_id == claim_case_id
    ).all()
    for doc in documents:
        try:
            file_bytes = read_file(doc.file_path)
        except FileNotFoundError:
            logger.warning(
                "Skipping missing attachment for claim_case=%s doc_id=%s path=%s",
                claim_case_id, doc.id, doc.file_path,
            )
            continue
        attachments.append((
            file_bytes,
            doc.original_filename,
            doc.content_type or "application/octet-stream",
        ))

    if is_onboarded:
        hospital = (
            db.query(Hospital)
            .filter(Hospital.id == claim_case.hospital_id)
            .first()
            if claim_case.hospital_id else None
        )
        from_email = hospital.email if hospital and hospital.email else "onboarded@oasys.local"
    else:
        from_email, from_password = _resolve_hospital_credentials(db, claim_case)
        send_email(
            from_email=from_email,
            from_password=from_password,
            to_email=to_email,
            subject=subject,
            body=content,
            attachments=attachments or None,
            cc_emails=cc_emails or None,
        )

    # Transition the workflow state based on the current outcome:
    #   APPROVED / PARTIALLY_APPROVED -> ENHANCE_SUBMITTED
    #   DENIED                        -> RECONSIDER
    #   ADR_NMI                       -> ADR_SUBMITTED
    next_state = QUERY_RAISE_STATE.get(claim_case.claim_status)
    if not next_state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot raise query from claim_status '{claim_case.claim_status}'. "
                f"Must be one of: {', '.join(sorted(QUERY_RAISE_STATE))}"
            ),
        )
    claim_case.status = next_state

    db.add(StatusHistory(
        claim_case_id=claim_case.id,
        stage=claim_case.current_stage,
        status=next_state,
        remarks=(
            "Query submitted to onboarded provider"
            if is_onboarded
            else f"Query email sent to {to_email}"
        ),
    ))

    email_record = ClaimCaseEmail(
        claim_case_id=claim_case.id,
        direction="SENT",
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body=content,
        thread_id=claim_case.thread_id,
        email_type=next_state,
        email_date=datetime.now(timezone.utc),
        is_read=True,
        provider_read=not is_onboarded,
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
        "to_email": to_email,
        "subject": subject,
        "status": claim_case.status,
    }


def get_inbox(limit: int = 10) -> list[dict]:
    return fetch_inbox(limit)
