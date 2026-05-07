from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.claim import Claim
from app.models.claim_case import ClaimCase
from app.models.claim_case_email import ClaimCaseEmail
from app.models.form_data import FormData
from app.models.cc_email import CcEmail
from app.models.policy_provider_config import PolicyProviderConfig
from app.models.query_log import QueryLog
from app.models.status_history import StatusHistory


def get_all_claims(
    db: Session,
    hospital_id: UUID | None,
    exclude_draft: bool = False,
    provider_id: UUID | None = None,
    policy_provider_id: UUID | None = None,
) -> list[dict]:
    query = db.query(ClaimCase)
    if policy_provider_id is not None:
        # INSURANCE_PROVIDER user: scope by their provider across all hospitals.
        query = query.filter(ClaimCase.policy_provider_id == policy_provider_id)
    else:
        query = query.filter(ClaimCase.hospital_id == hospital_id)

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
            "uhid": cc.uhid,
            "patient_name": patient_name,
            "claim_number": cc.claim_number if cc.claim_number and cc.claim_number != "null" else None,
            "claim_status": cc.current_stage,
            "provider_name": provider_name,
            "provider_id": provider_id_str,
            "amount": amount,
            "approved_amount": float(cc.approved_amount) if cc.approved_amount is not None else None,
            "status": cc.claim_status or cc.status,
            "workflow_status": cc.status,
            "created_at": cc.created_at,
        })

    return result


def _find_first_value(obj, keys: set[str]):
    """Recursively find first non-empty value matching any key in `keys` (case-insensitive)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in keys and v not in (None, "", [], {}):
                return v
        for v in obj.values():
            found = _find_first_value(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first_value(item, keys)
            if found is not None:
                return found
    return None


def get_claim_case(db: Session, claim_case_id, current_user=None) -> ClaimCase:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )
    if (
        current_user is not None
        and current_user.role == "INSURANCE_PROVIDER"
        and claim_case.policy_provider_id != current_user.policy_provider_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to access this claim case",
        )
    claim_case.unread_count = sum(1 for e in claim_case.emails if not e.is_read)
    # Newest history first.
    claim_case.status_history = sorted(
        claim_case.status_history, key=lambda x: x.created_at, reverse=True
    )

    # Fetch policy provider email
    provider = db.query(PolicyProviderConfig).filter(
        PolicyProviderConfig.id == claim_case.policy_provider_id
    ).first()
    claim_case.policy_provider_email = provider.email if provider else None
    claim_case.is_onboarded = bool(provider and provider.is_onboarded)

    # Fetch hospital (for the form-header block)
    from app.models.hospital import Hospital
    hospital = (
        db.query(Hospital).filter(Hospital.id == claim_case.hospital_id).first()
        if claim_case.hospital_id else None
    )

    claim_case.header_info = {
        "tpa_name": (provider.tpa_name if provider and provider.tpa_name else (provider.name if provider else None)),
        "tpa_toll_free_phone": provider.tpa_toll_free_phone if provider else None,
        "tpa_toll_free_fax": provider.tpa_toll_free_fax if provider else None,
        "hospital_name": hospital.name if hospital else None,
        "hospital_address": hospital.address if hospital else None,
        "hospital_rohini_id": hospital.rohini_id if hospital else None,
        "hospital_email": hospital.email if hospital else None,
    }

    # Fetch CC emails matching this hospital and/or provider
    cc_query = db.query(CcEmail)
    filters = []
    if claim_case.hospital_id:
        filters.append(CcEmail.hospital_id == claim_case.hospital_id)
    filters.append(CcEmail.policy_provider_id == claim_case.policy_provider_id)
    cc_emails = cc_query.filter(sa.or_(*filters)).all()
    claim_case.cc_emails = [cc.email for cc in cc_emails]

    # Build summary from the latest form_data (key names vary across templates,
    # so search the JSON recursively for the first matching field).
    latest_form = (
        db.query(FormData)
        .filter(FormData.claim_case_id == claim_case.id)
        .order_by(FormData.created_at.desc())
        .first()
    )
    data = latest_form.data_json if latest_form and latest_form.data_json else {}
    requested_amount = _find_first_value(
        data,
        {"requested_amount", "total_cost", "total_amount", "claim_amount", "estimated_amount"},
    )
    try:
        requested_amount = float(requested_amount) if requested_amount is not None else None
    except (TypeError, ValueError):
        requested_amount = None

    claim_case.summary = {
        "patient_name": _find_first_value(data, {"patient_name", "name"}),
        "uhid": claim_case.uhid,
        "provider_name": provider.name if provider else None,
        "diagnosis": _find_first_value(
            data,
            {"provisional_diagnosis", "diagnosis", "final_diagnosis"},
        ),
        "icd_10": _find_first_value(
            data,
            {"icd10_code", "icd_10_code", "icd_10", "icd10", "icd"},
        ),
        "requested_amount": requested_amount,
    }

    return claim_case


# Workflow states on ClaimCase.status
AWAITING_PROVIDER_STATUSES = {"SUBMITTED", "ENHANCE_SUBMITTED", "RECONSIDER", "ADR_SUBMITTED"}
OUTCOME_STATUSES = {"APPROVED", "PARTIALLY_APPROVED", "DENIED", "ADR_NMI"}
VALID_STATUSES = {"DRAFT"} | AWAITING_PROVIDER_STATUSES | OUTCOME_STATUSES | {"UNKNOWN"}

# Map the current outcome to the workflow state we move into when the hospital
# sends a reply (query / docs) back to the provider. See claim-flow diagram.
QUERY_RAISE_STATE = {
    "APPROVED": "ENHANCE_SUBMITTED",
    "PARTIALLY_APPROVED": "ENHANCE_SUBMITTED",
    "DENIED": "RECONSIDER",
    "ADR_NMI": "ADR_SUBMITTED",
}


def update_claim_case_status(
    db: Session, claim_case_id, new_status: str, remarks: str | None = None, user_id=None
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


VALID_CLAIM_STATUSES = OUTCOME_STATUSES | {"UNKNOWN"}
STATUS_TO_EMAIL_TYPE = {
    "APPROVED": "APPROVAL",
    "PARTIALLY_APPROVED": "PARTIAL_APPROVAL",
    "DENIED": "DENIAL",
    "ADR_NMI": "ADR_NMI",
}


def update_extracted_data(
    db: Session,
    claim_case_id,
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

    # Mark email as read
    email_record.is_read = True

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

        # Resolve open query logs on a terminal outcome (approved/partial/denied)
        if new_claim_status in ("APPROVED", "PARTIALLY_APPROVED", "DENIED"):
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

    # Update approved_amount (allow setting to null)
    if "approved_amount" in payload.model_fields_set:
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
