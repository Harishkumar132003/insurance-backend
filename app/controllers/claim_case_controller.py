from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.claim import Claim
from app.models.claim_case import ClaimCase
from app.models.claim_case_email import ClaimCaseEmail
from app.models.form_data import FormData
from app.models.policy_provider_config import PolicyProviderConfig
from app.models.query_log import QueryLog
from app.models.status_history import StatusHistory


def get_all_claims(
    db: Session,
    hospital_id: UUID | None,
    exclude_draft: bool = False,
    provider_id: UUID | None = None,
) -> list[dict]:
    query = db.query(ClaimCase).filter(ClaimCase.hospital_id == hospital_id)

    if exclude_draft:
        query = query.filter(ClaimCase.status != "DRAFT")

    if provider_id:
        query = query.filter(ClaimCase.policy_provider_id == provider_id)

    claim_cases = query.order_by(ClaimCase.created_at.desc()).all()

    result = []
    for cc in claim_cases:
        # Extract patient name from the latest form_data
        patient_name = None
        amount = None
        form_data = (
            db.query(FormData)
            .filter(FormData.claim_case_id == cc.id)
            .order_by(FormData.created_at.desc())
            .first()
        )
        if form_data and form_data.data_json:
            patient_insured = form_data.data_json.get("patient_insured", {})
            patient_name = patient_insured.get("patient_name")
            hospitalization = form_data.data_json.get("hospitalization", {})
            costs = hospitalization.get("costs", {})
            amount = costs.get("total_cost")

        # Get claimed_amount from Claim if it exists
        claim = db.query(Claim).filter(Claim.claim_case_id == cc.id).first()
        if claim and claim.claimed_amount is not None:
            amount = float(claim.claimed_amount)

        # Get provider details
        provider_name = None
        provider_id_str = None
        if cc.policy_provider_id:
            provider = (
                db.query(PolicyProviderConfig)
                .filter(PolicyProviderConfig.id == cc.policy_provider_id)
                .first()
            )
            if provider:
                provider_name = provider.name
                provider_id_str = provider.provider_id

        result.append({
            "claim_case_id": cc.id,
            "patient_name": patient_name,
            "claim_number": cc.claim_number if cc.claim_number and cc.claim_number != "null" else None,
            "claim_status": cc.current_stage,
            "provider_name": provider_name,
            "provider_id": provider_id_str,
            "amount": amount,
            "approved_amount": float(cc.approved_amount) if cc.approved_amount is not None else None,
            "status": cc.claim_status,
            "created_at": cc.created_at,
        })

    return result


def get_claim_case(db: Session, claim_case_id: int) -> ClaimCase:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )
    return claim_case


VALID_STATUSES = {"DRAFT", "APPLIED", "QUERY", "APPROVED", "REJECTED", "ADR", "UNKNOWN"}


def update_claim_case_status(
    db: Session, claim_case_id: int, new_status: str, remarks: str | None = None, user_id=None
) -> ClaimCase:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )

    if new_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    claim_case.status = new_status
    db.add(StatusHistory(
        claim_case_id=claim_case.id,
        stage="PRE_AUTH",
        status=new_status,
        remarks=remarks,
        updated_by=user_id,
    ))
    db.commit()
    db.refresh(claim_case)
    return claim_case


VALID_CLAIM_STATUSES = {"APPROVED", "REJECTED", "QUERY", "ADR", "UNKNOWN"}
STATUS_TO_EMAIL_TYPE = {
    "QUERY": "QUERY_RAISED",
    "ADR": "ADR",
    "APPROVED": "APPROVAL",
    "REJECTED": "REJECTION",
}


def update_extracted_data(
    db: Session,
    claim_case_id: int,
    email_id: int,
    payload,
    user_id=None,
) -> ClaimCase:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )

    email_record = (
        db.query(ClaimCaseEmail)
        .filter(
            ClaimCaseEmail.id == email_id,
            ClaimCaseEmail.claim_case_id == claim_case_id,
        )
        .first()
    )
    if not email_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email not found for this claim case",
        )

    # Update email_type: explicit value takes priority, otherwise auto-derive from claim_status
    if payload.email_type is not None:
        email_record.email_type = payload.email_type.upper()

    # Update claim_status
    if payload.claim_status is not None:
        new_claim_status = payload.claim_status.upper()
        if new_claim_status not in VALID_CLAIM_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid claim_status '{payload.claim_status}'. Must be one of: {', '.join(sorted(VALID_CLAIM_STATUSES))}",
            )
        claim_case.claim_status = new_claim_status

        # Auto-sync email_type from claim_status only if not explicitly provided
        if payload.email_type is None and new_claim_status in STATUS_TO_EMAIL_TYPE:
            email_record.email_type = STATUS_TO_EMAIL_TYPE[new_claim_status]

        # Resolve open query logs on APPROVED/REJECTED
        if new_claim_status in ("APPROVED", "REJECTED"):
            open_queries = (
                db.query(QueryLog)
                .filter(QueryLog.claim_case_id == claim_case.id, QueryLog.status == "OPEN")
                .all()
            )
            for q in open_queries:
                q.status = "RESOLVED"
                q.resolved_at = datetime.now(timezone.utc)

    # Update claim_number
    if payload.claim_number is not None:
        claim_case.claim_number = payload.claim_number

    # Update approved_amount
    if payload.approved_amount is not None:
        claim_case.approved_amount = payload.approved_amount

    # Add status history for audit
    db.add(StatusHistory(
        claim_case_id=claim_case.id,
        stage=claim_case.current_stage,
        status=payload.claim_status.upper() if payload.claim_status else claim_case.claim_status or "UNKNOWN",
        remarks="Manual edit of AI-extracted data",
        changed_by="MANUAL_EDIT",
        updated_by=user_id,
    ))

    db.commit()
    db.refresh(claim_case)
    return claim_case
