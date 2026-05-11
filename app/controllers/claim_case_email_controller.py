import math
from datetime import datetime, timezone

from fastapi import HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.claim_case import ClaimCase
from app.models.claim_case_email import ClaimCaseEmail
from app.models.claim_case_email_attachment import ClaimCaseEmailAttachment
from app.models.form_data import FormData
from app.models.hospital import Hospital
from app.models.policy_provider_config import PolicyProviderConfig
from app.models.query_log import QueryLog
from app.models.status_history import StatusHistory
from app.utils.file_storage import get_attachment_full_path, save_attachment


def get_all_claim_case_emails(
    db: Session,
    hospital_id,
    page: int = 1,
    page_size: int = 20,
    claim_case_id=None,
    policy_provider_id=None,
) -> dict:
    # Scope: by policy_provider_id (INSURANCE_PROVIDER user) or by hospital_id.
    if policy_provider_id is not None:
        scope_filter = ClaimCase.policy_provider_id == policy_provider_id
    else:
        scope_filter = ClaimCase.hospital_id == hospital_id

    # Subquery: latest email id per claim_case
    latest_subq_query = (
        db.query(func.max(ClaimCaseEmail.id).label("max_id"))
        .join(ClaimCase, ClaimCaseEmail.claim_case_id == ClaimCase.id)
        .filter(scope_filter)
    )
    if claim_case_id:
        latest_subq_query = latest_subq_query.filter(ClaimCaseEmail.claim_case_id == claim_case_id)
    latest_subq = latest_subq_query.group_by(ClaimCaseEmail.claim_case_id).subquery()

    base_query = (
        db.query(ClaimCaseEmail, ClaimCase.claim_number, PolicyProviderConfig.is_onboarded)
        .join(ClaimCase, ClaimCaseEmail.claim_case_id == ClaimCase.id)
        .outerjoin(
            PolicyProviderConfig,
            PolicyProviderConfig.id == ClaimCase.policy_provider_id,
        )
        .filter(scope_filter)
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
    for email, claim_number, is_onboarded in rows:
        items.append({
            "id": email.id,
            "claim_case_id": email.claim_case_id,
            "claim_number": claim_number,
            "is_onboard_claim": bool(is_onboarded),
            "direction": email.direction,
            "email_type": email.email_type,
            "from_email": email.from_email,
            "to_email": email.to_email,
            "subject": email.subject,
            "email_date": email.email_date,
            "is_read": email.is_read,
            "provider_read": email.provider_read,
            "ai_suggested_status": email.ai_suggested_status,
            "ai_suggested_claim_number": email.ai_suggested_claim_number,
            "ai_suggested_amount": float(email.ai_suggested_amount) if email.ai_suggested_amount is not None else None,
            "ai_query_details": email.ai_query_details,
            "ai_documents_requested": email.ai_documents_requested,
            "ai_documents_list": email.ai_documents_list,
            "form_values": email.form_values,
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
            "provider_read": e.provider_read,
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


def mark_email_as_read(db: Session, claim_case_id, email_id: int, current_user=None):
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

    if current_user is not None and current_user.role == "INSURANCE_PROVIDER":
        claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
        if not claim_case or claim_case.policy_provider_id != current_user.policy_provider_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to access this claim case",
            )
        email.provider_read = True
    else:
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

        from app.controllers.claim_case_controller import (
            coerce_outcome_for_prior_approval,
            STATUS_TO_EMAIL_TYPE,
        )

        # Apply AI suggestion to claim case. The provider's reply moves the
        # workflow back into the matching outcome state in the flow diagram.
        # Business rule: once any approved amount exists on the claim, the
        # initial APPROVED is the only "APPROVED" — a fresh APPROVED becomes
        # ENHANCEMENT_APPROVED and a fresh DENIED becomes ENHANCEMENT_DENIED
        # (the original approval still stands).
        applied_status = coerce_outcome_for_prior_approval(
            email.ai_suggested_status, claim_case.approved_amount
        )
        if applied_status != email.ai_suggested_status:
            # Keep the email row consistent with the coerced decision.
            email.ai_suggested_status = applied_status
            if applied_status in STATUS_TO_EMAIL_TYPE:
                email.email_type = STATUS_TO_EMAIL_TYPE[applied_status]
        claim_case.claim_status = applied_status
        claim_case.status = applied_status

        if email.ai_suggested_claim_number and not claim_case.claim_number:
            claim_case.claim_number = email.ai_suggested_claim_number

        round_amount = None
        if (
            applied_status in ("APPROVED", "PARTIALLY_APPROVED", "ENHANCEMENT_APPROVED")
            and email.ai_suggested_amount is not None
        ):
            round_amount = float(email.ai_suggested_amount)
            prior_total = float(claim_case.approved_amount or 0)
            claim_case.approved_amount = prior_total + round_amount

        # Create QueryLog when provider asks for docs / clarification
        if applied_status == "ADR_NMI":
            db.add(QueryLog(
                claim_case_id=claim_case.id,
                query_type=applied_status,
                query_details=email.ai_query_details or email.ai_summary,
                documents_requested=email.ai_documents_requested,
                documents_list=email.ai_documents_list,
                status="OPEN",
            ))

        # Resolve open QueryLogs on a terminal outcome
        if applied_status in (
            "APPROVED", "PARTIALLY_APPROVED", "DENIED",
            "ENHANCEMENT_APPROVED", "ENHANCEMENT_DENIED",
        ):
            open_queries = (
                db.query(QueryLog)
                .filter(QueryLog.claim_case_id == claim_case.id, QueryLog.status == "OPEN")
                .all()
            )
            for q in open_queries:
                q.status = "RESOLVED"
                q.resolved_at = datetime.now(timezone.utc)

        # Create StatusHistory
        base_remarks = remarks or email.ai_summary or "AI suggestion approved by user"
        if round_amount is not None:
            cumulative = float(claim_case.approved_amount or 0)
            amount_note = f"Approved this round: ₹{round_amount:,.2f} (cumulative: ₹{cumulative:,.2f})"
            base_remarks = f"{base_remarks} | {amount_note}" if base_remarks else amount_note
        db.add(StatusHistory(
            claim_case_id=claim_case.id,
            stage=claim_case.current_stage,
            status=email.ai_suggested_status,
            remarks=base_remarks,
            approved_amount=round_amount,
            email_id=email.id,
            changed_by="EMAIL_VALIDATED",
            updated_by=user_id,
        ))

    db.commit()
    db.refresh(email)
    return email


def get_provider_queue(
    db: Session, policy_provider_id, page: int = 1, page_size: int = 20
) -> dict:
    from app.controllers.claim_case_controller import AWAITING_PROVIDER_STATUSES

    base_query = db.query(ClaimCase).filter(
        ClaimCase.policy_provider_id == policy_provider_id,
        ClaimCase.status.in_(list(AWAITING_PROVIDER_STATUSES)),
    )
    total = base_query.count()
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    offset = (page - 1) * page_size

    rows = (
        base_query.order_by(ClaimCase.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    hospital_ids = {r.hospital_id for r in rows if r.hospital_id}
    hospitals = {}
    if hospital_ids:
        for h in db.query(Hospital).filter(Hospital.id.in_(hospital_ids)).all():
            hospitals[h.id] = h.name

    items = []
    for cc in rows:
        patient_name = None
        amount = None
        form_data = (
            db.query(FormData)
            .filter(FormData.claim_case_id == cc.id)
            .order_by(FormData.created_at.desc())
            .first()
        )
        if form_data and form_data.data_json:
            patient_insured = form_data.data_json.get("patient_insured", {}) or {}
            patient_name = patient_insured.get("patient_name")
            hospitalization = form_data.data_json.get("hospitalization", {}) or {}
            costs = hospitalization.get("costs", {}) or {}
            amount = costs.get("total_cost")

        items.append({
            "claim_case_id": cc.id,
            "uhid": cc.uhid,
            "patient_name": patient_name,
            "claim_number": cc.claim_number if cc.claim_number and cc.claim_number != "null" else None,
            "hospital_id": cc.hospital_id,
            "hospital_name": hospitals.get(cc.hospital_id),
            "amount": float(amount) if amount is not None else None,
            "status": cc.status,
            "created_at": cc.created_at,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


_PROVIDER_ACTION_STATUSES = {
    "APPROVED", "PARTIALLY_APPROVED", "DENIED",
    "ENHANCEMENT_APPROVED", "ENHANCEMENT_DENIED", "ADR_NMI",
}


def process_by_provider(
    db: Session,
    claim_case_id,
    current_user,
    new_status: str,
    approved_amount: float | None,
    claim_number: str | None,
    remarks: str | None,
    query_details: str | None,
    documents_requested: str | None,
    documents_list: list[str] | None = None,
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
    attachment_content_type: str | None = None,
):
    from app.controllers.claim_case_controller import (
        AWAITING_PROVIDER_STATUSES,
        STATUS_TO_EMAIL_TYPE,
        coerce_outcome_for_prior_approval,
    )

    if new_status not in _PROVIDER_ACTION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(_PROVIDER_ACTION_STATUSES)}",
        )

    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )

    if claim_case.policy_provider_id != current_user.policy_provider_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to act on this claim case",
        )

    if claim_case.status not in AWAITING_PROVIDER_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Claim case is not awaiting provider action (status={claim_case.status})",
        )

    provider = (
        db.query(PolicyProviderConfig)
        .filter(PolicyProviderConfig.id == claim_case.policy_provider_id)
        .first()
    )
    hospital = (
        db.query(Hospital).filter(Hospital.id == claim_case.hospital_id).first()
        if claim_case.hospital_id else None
    )

    # Business rule: once a claim has any approved amount on record, the initial
    # APPROVED is the only "APPROVED" — a fresh APPROVED becomes
    # ENHANCEMENT_APPROVED and a fresh DENIED becomes ENHANCEMENT_DENIED (the
    # original approval still stands). Coerce against the pre-update cumulative
    # so the new round's delta is added below.
    new_status = coerce_outcome_for_prior_approval(new_status, claim_case.approved_amount)

    claim_case.claim_status = new_status
    claim_case.status = new_status

    if claim_number and not claim_case.claim_number:
        claim_case.claim_number = claim_number

    round_amount = None
    if (
        new_status in ("APPROVED", "PARTIALLY_APPROVED", "ENHANCEMENT_APPROVED")
        and approved_amount is not None
    ):
        round_amount = float(approved_amount)
        prior_total = float(claim_case.approved_amount or 0)
        claim_case.approved_amount = prior_total + round_amount

    if new_status == "ADR_NMI":
        if documents_list is None:
            from app.services.document_extraction_service import extract_documents
            source = " ".join(filter(None, [documents_requested, query_details, remarks]))
            documents_list = extract_documents(source)
        db.add(QueryLog(
            claim_case_id=claim_case.id,
            query_type=new_status,
            query_details=query_details or remarks,
            documents_requested=documents_requested,
            documents_list=documents_list,
            status="OPEN",
        ))
    else:
        documents_list = None

    if new_status in (
        "APPROVED", "PARTIALLY_APPROVED", "DENIED",
        "ENHANCEMENT_APPROVED", "ENHANCEMENT_DENIED",
    ):
        open_queries = (
            db.query(QueryLog)
            .filter(QueryLog.claim_case_id == claim_case.id, QueryLog.status == "OPEN")
            .all()
        )
        for q in open_queries:
            q.status = "RESOLVED"
            q.resolved_at = datetime.now(timezone.utc)

    # Structured snapshot of what the provider entered, so the timeline's
    # "View Form" can render the decision form read-only (claim number,
    # approved amount, remarks, requested documents …).
    provider_form_values = {
        "decision": new_status,
        "claim_number": claim_number or claim_case.claim_number or "",
        "approved_amount": (round_amount if round_amount is not None else None),
        "cumulative_approved_amount": float(claim_case.approved_amount or 0),
        "remarks": remarks or "",
        "query_details": query_details or "",
        "documents_requested": documents_requested or "",
        "documents_list": list(documents_list) if documents_list else [],
    }

    # Synthetic RECEIVED email so the existing timeline renders this action
    # the same way as an AI-extracted reply from an external provider.
    # Created BEFORE the StatusHistory so the latter can carry email_id.
    synthetic_email = ClaimCaseEmail(
        claim_case_id=claim_case.id,
        direction="RECEIVED",
        from_email=(provider.email if provider and provider.email else "provider@oasys.local"),
        to_email=(hospital.email if hospital and hospital.email else "hospital@oasys.local"),
        subject=f"Provider decision [{claim_case.thread_id or ''}]".strip(),
        body=remarks or query_details,
        form_values=provider_form_values,
        thread_id=claim_case.thread_id,
        email_type=STATUS_TO_EMAIL_TYPE.get(new_status),
        email_date=datetime.now(timezone.utc),
        is_read=False,
        provider_read=True,
        ai_suggested_status=new_status,
        ai_suggested_amount=approved_amount,
        ai_suggested_claim_number=claim_number,
        ai_summary=remarks,
        ai_query_details=query_details,
        ai_documents_requested=documents_requested,
        ai_documents_list=documents_list,
        validation_status="APPROVED",
        validated_at=datetime.now(timezone.utc),
        validated_by=current_user.id,
    )
    db.add(synthetic_email)
    db.flush()  # synthetic_email.id needed for StatusHistory.email_id and any attachment row

    base_remarks = remarks or query_details or "Processed by insurance provider"
    if round_amount is not None:
        cumulative = float(claim_case.approved_amount or 0)
        amount_note = f"Approved this round: ₹{round_amount:,.2f} (cumulative: ₹{cumulative:,.2f})"
        base_remarks = f"{base_remarks} | {amount_note}" if base_remarks else amount_note
    db.add(StatusHistory(
        claim_case_id=claim_case.id,
        stage=claim_case.current_stage,
        status=new_status,
        remarks=base_remarks,
        approved_amount=round_amount,
        email_id=synthetic_email.id,
        changed_by="PROVIDER_ACTION",
        updated_by=current_user.id,
    ))

    # Provider-uploaded approval letter (or other supporting file) — only
    # accepted on outcome statuses; ADR_NMI uses documents_list instead.
    if (
        attachment_bytes
        and attachment_filename
        and new_status in (
            "APPROVED", "PARTIALLY_APPROVED", "DENIED",
            "ENHANCEMENT_APPROVED", "ENHANCEMENT_DENIED",
        )
    ):
        stored_filename, file_path = save_attachment(
            claim_case.id, attachment_bytes, attachment_filename
        )
        db.add(ClaimCaseEmailAttachment(
            email_id=synthetic_email.id,
            claim_case_id=claim_case.id,
            original_filename=attachment_filename,
            stored_filename=stored_filename,
            file_path=file_path,
            content_type=attachment_content_type,
            file_size=len(attachment_bytes),
        ))

    db.commit()
    db.refresh(claim_case)
    return claim_case


def get_submissions_and_responses(db: Session, claim_case_id) -> dict:
    """Return a flat, time-ordered list of every file on this claim:
    - DRAFT: uploaded via /documents but not yet attached to a sent email
    - SENT:  hospital submissions (each round)
    - RECEIVED: provider replies (any attachments they sent back)"""
    from app.models.claim_case_document import ClaimCaseDocument

    files = []

    # DRAFT files — uploaded directly to the claim, not yet attached to an
    # email. Once a doc goes out (sent_email_id set) it also exists as a
    # ClaimCaseEmailAttachment below, so exclude it here to avoid listing it
    # twice.
    docs = (
        db.query(ClaimCaseDocument)
        .filter(
            ClaimCaseDocument.claim_case_id == claim_case_id,
            ClaimCaseDocument.sent_email_id.is_(None),
        )
        .order_by(ClaimCaseDocument.created_at.asc())
        .all()
    )
    for d in docs:
        files.append({
            "id": d.id,
            "email_id": None,
            "filename": d.original_filename,
            "content_type": d.content_type,
            "file_size": d.file_size,
            "direction": "DRAFT",
            "email_type": None,
            "view_url": f"/api/v1/claim-cases/{claim_case_id}/documents/{d.id}/view",
            "download_url": f"/api/v1/claim-cases/{claim_case_id}/documents/{d.id}/download",
            "created_at": d.created_at,
        })

    # SENT and RECEIVED files — attachments on every email row
    emails = (
        db.query(ClaimCaseEmail)
        .options(joinedload(ClaimCaseEmail.attachments))
        .filter(ClaimCaseEmail.claim_case_id == claim_case_id)
        .order_by(ClaimCaseEmail.created_at.asc())
        .all()
    )
    for e in emails:
        for a in e.attachments:
            files.append({
                "id": a.id,
                "email_id": e.id,
                "filename": a.original_filename,
                "content_type": a.content_type,
                "file_size": a.file_size,
                "direction": e.direction,
                "email_type": e.email_type,
                "view_url": f"/api/v1/claim-cases/{claim_case_id}/emails/{e.id}/attachments/{a.id}/view",
                "download_url": f"/api/v1/claim-cases/{claim_case_id}/emails/{e.id}/attachments/{a.id}/download",
                "created_at": a.created_at,
            })

    files.sort(key=lambda f: f["created_at"])
    return {"files": files}
