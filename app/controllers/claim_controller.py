import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.controllers.email_controller import _resolve_hospital_credentials, _resolve_thread_context, _threaded_subject
from app.models.claim import Claim
from app.models.claim_case import ClaimCase
from app.models.claim_case_document import ClaimCaseDocument
from app.models.claim_case_email import ClaimCaseEmail
from app.models.claim_case_email_attachment import ClaimCaseEmailAttachment
from app.models.form_data import FormData
from app.models.claim_bill_item import ClaimBillItem
from app.models.hospital import Hospital
from app.models.policy_provider_config import PolicyProviderConfig
from app.models.status_history import StatusHistory
from app.models.user import User
from app.schemas.claim import (
    BillBreakdownItem,
    ClaimCreate,
    ClaimDocumentGroup,
    ClaimDraftResponse,
    ClaimDraftSave,
    ClaimResponse,
)
from app.schemas.claim_case_document import ClaimCaseDocumentResponse
from app.services.email_service import send_email
from app.utils.file_storage import read_file, save_attachment


logger = logging.getLogger(__name__)


def _scope_to_user(claim_case: ClaimCase, current_user: User) -> None:
    """Reject access when the current user can't act on this claim case."""
    if current_user.role == "HOSPITAL_ADMIN" and claim_case.hospital_id != current_user.hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to access this claim case",
        )
    if (
        current_user.role == "INSURANCE_PROVIDER"
        and claim_case.policy_provider_id != current_user.policy_provider_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to access this claim case",
        )


def _build_response(
    db: Session,
    claim_case: ClaimCase,
    claim: Claim,
    *,
    is_onboarded: bool,
    email_record_id: int | None,
) -> ClaimResponse:
    # Latest claim-stage form row (written on raise) holds the breakdown.
    form = (
        db.query(FormData)
        .filter(FormData.claim_case_id == claim_case.id, FormData.stage == "CLAIM")
        .order_by(FormData.created_at.desc())
        .first()
    )
    bill_breakdown: list[BillBreakdownItem] = []
    remarks: str | None = None
    if form is not None:
        for item in form.bill_items:
            bill_breakdown.append(
                BillBreakdownItem(label=item.label, amount=Decimal(str(item.amount)))
            )
        remarks = form.remarks

    docs = (
        db.query(ClaimCaseDocument)
        .filter(
            ClaimCaseDocument.claim_case_id == claim_case.id,
            ClaimCaseDocument.document_type.isnot(None),
        )
        .order_by(ClaimCaseDocument.created_at)
        .all()
    )
    grouped: dict[str, list[ClaimCaseDocumentResponse]] = {}
    for d in docs:
        grouped.setdefault(d.document_type, []).append(ClaimCaseDocumentResponse.model_validate(d))
    documents_by_type = [
        ClaimDocumentGroup(document_type=k, documents=v) for k, v in grouped.items()
    ]

    return ClaimResponse(
        id=claim.id,
        claim_case_id=claim_case.id,
        claimed_amount=claim.claimed_amount,
        approved_amount=claim.approved_amount,
        status=claim.status,
        submitted_at=claim.submitted_at,
        processed_at=claim.processed_at,
        created_at=claim.created_at,
        bill_breakdown=bill_breakdown,
        remarks=remarks,
        documents_by_type=documents_by_type,
        email_record_id=email_record_id,
        is_onboarded=is_onboarded,
    )


def raise_claim(
    db: Session,
    claim_case_id,
    payload: ClaimCreate,
    current_user: User,
) -> ClaimResponse:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim case not found")
    _scope_to_user(claim_case, current_user)
    if claim_case.case_status == "CANCELLED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Case is cancelled — no further action is allowed",
        )

    approved = float(claim_case.approved_amount or 0)
    if approved <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Claim can only be raised once some amount has been approved on the pre-auth",
        )

    existing = db.query(Claim).filter(Claim.claim_case_id == claim_case.id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Claim has already been raised for this case",
        )

    # Server-side check: sum(items) ≈ claimed_amount (±0.01).
    items_sum = sum((Decimal(str(i.amount)) for i in payload.bill_breakdown), Decimal("0"))
    if abs(items_sum - Decimal(str(payload.claimed_amount))) > Decimal("0.01"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bill breakdown items must sum to claimed_amount",
        )

    provider = (
        db.query(PolicyProviderConfig)
        .filter(PolicyProviderConfig.id == claim_case.policy_provider_id)
        .first()
    )
    is_onboarded = bool(provider and provider.is_onboarded)

    draft_form = _find_claim_draft(db, claim_case.id)
    if draft_form is not None:
        claim_form = draft_form
        claim_form.status = "SUBMITTED"
    else:
        claim_form = FormData(
            claim_case_id=claim_case.id,
            stage="CLAIM",
            status="SUBMITTED",
        )
        db.add(claim_form)
    claim_form.stage = "CLAIM"
    claim_form.claimed_amount = payload.claimed_amount
    claim_form.remarks = payload.remarks
    db.flush()
    _replace_bill_items(db, claim_form, payload.bill_breakdown)

    claim = Claim(
        claim_case_id=claim_case.id,
        claimed_amount=payload.claimed_amount,
        status="SUBMITTED",
    )
    db.add(claim)
    db.flush()

    # Email threading + subject (matches send_form_email).
    in_reply_to, references, root_subject = _resolve_thread_context(db, claim_case.id)
    if not claim_case.thread_id:
        claim_case.thread_id = uuid.uuid4().hex[:12]
    subject = _threaded_subject(f"{payload.email_subject} [{claim_case.thread_id}]", root_subject)

    # Attach categorized (claim-stage) documents that haven't been sent yet.
    pending_docs = (
        db.query(ClaimCaseDocument)
        .filter(
            ClaimCaseDocument.claim_case_id == claim_case.id,
            ClaimCaseDocument.sent_email_id.is_(None),
            ClaimCaseDocument.document_type.isnot(None),
        )
        .all()
    )
    attachments: list[tuple[bytes, str, str]] = []
    attached_docs: list[ClaimCaseDocument] = []
    attachment_doc_types: list[str | None] = []
    for doc in pending_docs:
        try:
            file_bytes = read_file(doc.file_path)
        except FileNotFoundError:
            logger.warning(
                "Skipping missing claim attachment claim_case=%s doc_id=%s path=%s",
                claim_case.id, doc.id, doc.file_path,
            )
            continue
        attachments.append((file_bytes, doc.original_filename, doc.content_type or "application/octet-stream"))
        attached_docs.append(doc)
        attachment_doc_types.append(doc.document_type)

    sent_message_id: str | None = None
    if is_onboarded:
        hospital = (
            db.query(Hospital).filter(Hospital.id == claim_case.hospital_id).first()
            if claim_case.hospital_id else None
        )
        from_email = hospital.email if hospital and hospital.email else "onboarded@oasys.local"
        to_email = (provider.email if provider else None) or "onboarded@oasys.local"
    else:
        if not provider or not provider.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Policy provider has no email configured",
            )
        from_email, from_password = _resolve_hospital_credentials(db, claim_case)
        to_email = provider.email
        sent_message_id = send_email(
            from_email=from_email,
            from_password=from_password,
            to_email=to_email,
            subject=subject,
            body=payload.email_body,
            attachments=attachments or None,
            cc_emails=None,
            in_reply_to=in_reply_to,
            references=references or None,
        )

    email_record = ClaimCaseEmail(
        claim_case_id=claim_case.id,
        direction="SENT",
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body=payload.email_body,
        form_values={
            "bill_breakdown": [
                {"label": i.label, "amount": str(i.amount)} for i in payload.bill_breakdown
            ],
            "claimed_amount": str(payload.claimed_amount),
            "remarks": payload.remarks,
        },
        thread_id=claim_case.thread_id,
        message_id=sent_message_id,
        email_type="CLAIM_SUBMITTED",
        email_date=datetime.now(timezone.utc),
        is_read=True,
        provider_read=not is_onboarded,
    )
    db.add(email_record)
    db.flush()

    for doc in attached_docs:
        doc.sent_email_id = email_record.id

    for (file_bytes, filename, content_type), doc_type in zip(attachments, attachment_doc_types):
        stored_filename, file_path = save_attachment(claim_case.id, file_bytes, filename)
        db.add(ClaimCaseEmailAttachment(
            email_id=email_record.id,
            claim_case_id=claim_case.id,
            original_filename=filename,
            stored_filename=stored_filename,
            file_path=file_path,
            content_type=content_type,
            file_size=len(file_bytes),
            document_type=doc_type,
        ))

    claim_case.current_stage = "CLAIM"
    claim_case.case_status = "CLAIM_SUBMITTED"
    db.add(StatusHistory(
        claim_case_id=claim_case.id,
        stage="CLAIM",
        status="SUBMITTED",
        email_id=email_record.id,
        remarks=payload.remarks or (
            "Submitted to onboarded provider" if is_onboarded else f"Email sent to {to_email}"
        ),
        updated_by=current_user.id,
    ))

    db.commit()
    db.refresh(claim)
    db.refresh(claim_case)

    return _build_response(
        db, claim_case, claim, is_onboarded=is_onboarded, email_record_id=email_record.id
    )


def get_claim(db: Session, claim_case_id, current_user: User) -> ClaimResponse:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim case not found")
    _scope_to_user(claim_case, current_user)

    claim = db.query(Claim).filter(Claim.claim_case_id == claim_case.id).first()
    if not claim:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No claim raised for this case")

    provider = (
        db.query(PolicyProviderConfig)
        .filter(PolicyProviderConfig.id == claim_case.policy_provider_id)
        .first()
    )
    is_onboarded = bool(provider and provider.is_onboarded)

    # The submission email is the latest SENT email_type=CLAIM_SUBMITTED.
    submission_email = (
        db.query(ClaimCaseEmail)
        .filter(
            ClaimCaseEmail.claim_case_id == claim_case.id,
            ClaimCaseEmail.email_type == "CLAIM_SUBMITTED",
            ClaimCaseEmail.direction == "SENT",
        )
        .order_by(ClaimCaseEmail.created_at.desc())
        .first()
    )

    return _build_response(
        db, claim_case, claim,
        is_onboarded=is_onboarded,
        email_record_id=submission_email.id if submission_email else None,
    )


def _replace_bill_items(db: Session, form_data: FormData, items) -> None:
    """Replace the claim-stage bill_breakdown lines on a form row."""
    db.query(ClaimBillItem).filter(ClaimBillItem.form_data_id == form_data.id).delete(
        synchronize_session=False
    )
    for idx, it in enumerate(items or []):
        db.add(ClaimBillItem(
            form_data_id=form_data.id,
            label=it.label,
            amount=it.amount,
            sort_order=idx,
        ))


def _find_claim_draft(db: Session, claim_case_id) -> FormData | None:
    return (
        db.query(FormData)
        .filter(
            FormData.claim_case_id == claim_case_id,
            FormData.status == "DRAFT",
            FormData.stage == "CLAIM",
        )
        .order_by(FormData.created_at.desc())
        .first()
    )


def _draft_to_response(draft: FormData | None) -> ClaimDraftResponse:
    if draft is None:
        return ClaimDraftResponse(is_persisted=False)
    items = [
        BillBreakdownItem(label=it.label, amount=Decimal(str(it.amount)))
        for it in draft.bill_items
    ]
    claimed = Decimal(str(draft.claimed_amount)) if draft.claimed_amount is not None else None
    return ClaimDraftResponse(
        is_persisted=True,
        bill_breakdown=items,
        claimed_amount=claimed,
        remarks=draft.remarks,
        updated_at=draft.updated_at or draft.created_at,
    )


def get_claim_draft(db: Session, claim_case_id, current_user: User) -> ClaimDraftResponse:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim case not found")
    _scope_to_user(claim_case, current_user)
    return _draft_to_response(_find_claim_draft(db, claim_case.id))


def save_claim_draft(
    db: Session, claim_case_id, payload: ClaimDraftSave, current_user: User,
) -> ClaimDraftResponse:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim case not found")
    _scope_to_user(claim_case, current_user)

    if db.query(Claim).filter(Claim.claim_case_id == claim_case.id).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Claim has already been raised; drafts are no longer applicable",
        )

    draft = _find_claim_draft(db, claim_case.id)
    if draft is None:
        draft = FormData(
            claim_case_id=claim_case.id,
            stage="CLAIM",
            status="DRAFT",
        )
        db.add(draft)
    draft.stage = "CLAIM"
    draft.claimed_amount = payload.claimed_amount
    draft.remarks = payload.remarks
    db.flush()
    _replace_bill_items(db, draft, payload.bill_breakdown)

    db.commit()
    db.refresh(draft)
    return _draft_to_response(draft)


def delete_claim_draft(db: Session, claim_case_id, current_user: User) -> None:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim case not found")
    _scope_to_user(claim_case, current_user)

    draft = _find_claim_draft(db, claim_case.id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No draft to delete")

    # Files uploaded for this draft live as ClaimCaseDocument rows with
    # sent_email_id=NULL. Clean them up so the next attempt starts fresh.
    db.query(ClaimCaseDocument).filter(
        ClaimCaseDocument.claim_case_id == claim_case.id,
        ClaimCaseDocument.sent_email_id.is_(None),
    ).delete(synchronize_session=False)

    db.delete(draft)
    db.commit()
