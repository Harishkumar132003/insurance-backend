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
    q: str | None = None,
    stage: str | None = None,
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

    if stage:
        query = query.filter(ClaimCase.current_stage == stage)

    # Search: matches UHID directly OR a patient_name on any FormData row for
    # this claim (form_data.data_json -> patient_insured -> patient_name).
    # Case-insensitive substring match. Empty string is ignored.
    if q and q.strip():
        needle = f"%{q.strip()}%"
        patient_name_match = (
            sa.exists()
            .where(FormData.claim_case_id == ClaimCase.id)
            .where(
                FormData.data_json["patient_insured"]["patient_name"]
                .astext.ilike(needle)
            )
        )
        query = query.filter(
            sa.or_(ClaimCase.uhid.ilike(needle), patient_name_match)
        )

    claim_cases = query.order_by(ClaimCase.created_at.desc()).all()

    result = []
    for cc in claim_cases:
        # Extract patient + treatment details from the latest PRE_AUTH form_data.
        # The claim raise inserts a separate form_data row tagged stage='CLAIM'
        # that only holds the bill breakdown — it must be excluded here so the
        # list keeps showing patient / diagnosis / requested amount from the
        # original pre-auth submission.
        patient_name = None
        amount = None
        age = None
        gender = None
        diagnosis = None
        icd_10 = None
        form_data = (
            db.query(FormData)
            .filter(FormData.claim_case_id == cc.id)
            .filter(sa.or_(
                FormData.data_json.is_(None),
                FormData.data_json["stage"].astext.is_(None),
                FormData.data_json["stage"].astext != "CLAIM",
            ))
            .order_by(FormData.created_at.desc())
            .first()
        )
        if form_data and form_data.data_json:
            dj = form_data.data_json
            patient_insured = dj.get("patient_insured", {}) or {}
            patient_name = patient_insured.get("patient_name")
            age = patient_insured.get("age_years") or patient_insured.get("age")
            gender = patient_insured.get("gender")
            hospitalization = dj.get("hospitalization", {}) or {}
            costs = hospitalization.get("costs", {}) or {}
            amount = costs.get("total_cost")
            treating_doctor = dj.get("treating_doctor", {}) or {}
            diagnosis = treating_doctor.get("provisional_diagnosis") or treating_doctor.get("diagnosis")
            icd_10 = treating_doctor.get("icd10_code") or treating_doctor.get("icd_10")

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

        # Unread email count (drives the "N new" badge on the list card).
        unread_count = sum(1 for e in cc.emails if not e.is_read)

        result.append({
            "claim_case_id": cc.id,
            "uhid": cc.uhid,
            "patient_name": patient_name,
            "age": age,
            "gender": gender,
            "diagnosis": diagnosis,
            "icd_10": icd_10,
            "claim_number": cc.claim_number if cc.claim_number and cc.claim_number != "null" else None,
            "claim_status": cc.current_stage,
            "provider_name": provider_name,
            "provider_id": provider_id_str,
            "amount": amount,
            "approved_amount": float(cc.approved_amount) if cc.approved_amount is not None else None,
            "status": cc.claim_status or cc.status,
            "workflow_status": cc.status,
            "unread_count": unread_count,
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
    # Claim raise inserts a FormData row tagged stage='CLAIM' holding the bill
    # breakdown — it has no requested_amount / total_cost fields. The patient /
    # diagnosis / requested-amount summary on this endpoint is about the
    # PRE_AUTH form, so skip claim-stage form_data rows when picking the latest.
    latest_form = (
        db.query(FormData)
        .filter(FormData.claim_case_id == claim_case.id)
        .filter(sa.or_(
            FormData.data_json.is_(None),
            FormData.data_json["stage"].astext.is_(None),
            FormData.data_json["stage"].astext != "CLAIM",
        ))
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

    # Flag whether a Claim row has been raised against this case so the FE can
    # toggle the "Raise Claim" vs "View Claim" CTA without a separate request.
    # When one exists, attach a small summary so the detail page can display
    # claim totals without round-tripping to /claim.
    existing_claim = db.query(Claim).filter(Claim.claim_case_id == claim_case.id).first()
    claim_case.has_claim = existing_claim is not None
    claim_case.claim_summary = (
        {
            "claimed_amount": float(existing_claim.claimed_amount) if existing_claim.claimed_amount is not None else None,
            "approved_amount": float(existing_claim.approved_amount) if existing_claim.approved_amount is not None else None,
            "status": existing_claim.status,
        }
        if existing_claim
        else None
    )

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

    # Headline status for the FE card. Compared at the claim level: money
    # approved so far vs the requested/billed amount on the latest form_data.
    approved = float(claim_case.approved_amount or 0)
    if approved <= 0:
        # No money approved yet — surface the most informative status we have.
        claim_case.main_status = (
            claim_case.claim_status or claim_case.status or "UNKNOWN"
        )
    elif requested_amount is not None and approved < float(requested_amount):
        claim_case.main_status = "PARTIALLY_APPROVED"
    else:
        # approved >= requested, or requested is unknown (no estimate on
        # form_data) but money was sanctioned → treat as fully approved.
        claim_case.main_status = "APPROVED"

    return claim_case


# Workflow states on ClaimCase.status
AWAITING_PROVIDER_STATUSES = {
    "SUBMITTED", "ENHANCE_SUBMITTED", "RECONSIDER", "ADR_SUBMITTED",
    "CLAIM_SUBMITTED", "CLAIM_ADR_SUBMITTED", "CLAIM_RECONSIDER",
}
OUTCOME_STATUSES = {
    "APPROVED", "PARTIALLY_APPROVED", "DENIED",
    "ENHANCEMENT_APPROVED", "ENHANCEMENT_DENIED", "ADR_NMI",
}
VALID_STATUSES = {"DRAFT"} | AWAITING_PROVIDER_STATUSES | OUTCOME_STATUSES | {"UNKNOWN"}

# Map the current outcome to the workflow state we move into when the hospital
# sends a reply (query / docs) back to the provider. See claim-flow diagram.
# ENHANCEMENT_APPROVED / ENHANCEMENT_DENIED → ENHANCE_SUBMITTED: the hospital
# can file (or re-file) an enhancement request from either outcome.
QUERY_RAISE_STATE = {
    "APPROVED": "ENHANCE_SUBMITTED",
    "PARTIALLY_APPROVED": "ENHANCE_SUBMITTED",
    "DENIED": "RECONSIDER",
    "ENHANCEMENT_APPROVED": "ENHANCE_SUBMITTED",
    "ENHANCEMENT_DENIED": "ENHANCE_SUBMITTED",
    "ADR_NMI": "ADR_SUBMITTED",
}

# Claim-stage equivalent: when the hospital replies on a claim, the current
# workflow status on the case (CLAIM_ADR_NMI / CLAIM_DENIED) maps to a new
# workflow status that hands the ball back to the provider.
CLAIM_QUERY_RAISE_STATE = {
    "CLAIM_ADR_NMI": "CLAIM_ADR_SUBMITTED",
    "CLAIM_DENIED": "CLAIM_RECONSIDER",
}
# Maps the new workflow state to the un-prefixed status we write on the
# `claims` table (Claim's own state).
CLAIM_REPLY_TO_CLAIM_STATUS = {
    "CLAIM_ADR_SUBMITTED": "ADR_SUBMITTED",
    "CLAIM_RECONSIDER": "RECONSIDER",
}
# Email type for the outgoing email row when the hospital replies on a claim.
CLAIM_REPLY_EMAIL_TYPE = {
    "CLAIM_ADR_SUBMITTED": "CLAIM_ADR_SUBMITTED",
    "CLAIM_RECONSIDER": "CLAIM_RECONSIDER",
}


# Once a claim has any approved amount on record, the initial APPROVED is the
# only "APPROVED" — every subsequent approval is an ENHANCEMENT_APPROVED, and
# every rejection is an ENHANCEMENT_DENIED (the original approval still stands).
# Helper so the provider-action / validate-suggestion / manual-edit paths all
# coerce identically.
def coerce_outcome_for_prior_approval(new_status: str, prior_approved_amount) -> str:
    if float(prior_approved_amount or 0) <= 0:
        return new_status
    if new_status == "APPROVED":
        return "ENHANCEMENT_APPROVED"
    if new_status == "DENIED":
        return "ENHANCEMENT_DENIED"
    return new_status


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
    "ENHANCEMENT_APPROVED": "ENHANCEMENT_APPROVAL",
    "ENHANCEMENT_DENIED": "ENHANCEMENT_DENIAL",
    "ADR_NMI": "ADR_NMI",
}

# Same set of provider outcomes, but applied to a CLAIM-stage case.
# `claims.status` keeps the un-prefixed value (the claim's own state). The
# claim_case workflow status gets a CLAIM_-prefix so the same row doesn't
# collide with pre-auth states.
CLAIM_STATUS_TO_EMAIL_TYPE = {
    "APPROVED": "CLAIM_APPROVAL",
    "PARTIALLY_APPROVED": "CLAIM_PARTIAL_APPROVAL",
    "DENIED": "CLAIM_DENIAL",
    "ADR_NMI": "CLAIM_ADR_NMI",
}
CLAIM_OUTCOME_TO_CASE_STATUS = {
    "APPROVED": "CLAIM_APPROVED",
    "PARTIALLY_APPROVED": "CLAIM_PARTIALLY_APPROVED",
    "DENIED": "CLAIM_DENIED",
    "ADR_NMI": "CLAIM_ADR_NMI",
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

    is_claim_stage = claim_case.current_stage == "CLAIM"

    # Update email_type: explicit value takes priority, otherwise auto-derive
    # from claim_status (mapping picked below based on stage).
    if payload.email_type is not None:
        email_record.email_type = payload.email_type.upper()

    # `applied_status` is the bare, post-coercion outcome (APPROVED /
    # PARTIALLY_APPROVED / DENIED / ENHANCEMENT_* / ADR_NMI / UNKNOWN). It
    # flows through every downstream block. On claim stage we coerce
    # ENHANCEMENT_* → bare (no enhancement loop). On pre-auth we run the
    # existing "prior approved → next becomes ENHANCEMENT" coercion.
    applied_status: str | None = None
    if payload.claim_status is not None:
        candidate = payload.claim_status.upper()
        if candidate not in VALID_CLAIM_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid claim_status '{payload.claim_status}'. Must be one of: {', '.join(sorted(VALID_CLAIM_STATUSES))}",
            )

        if is_claim_stage:
            # Claim has no enhancement loop. Coerce defensively in case the
            # FE / AI emits one.
            if candidate == "ENHANCEMENT_APPROVED":
                candidate = "APPROVED"
            elif candidate == "ENHANCEMENT_DENIED":
                candidate = "DENIED"
            if candidate != "UNKNOWN" and candidate not in CLAIM_OUTCOME_TO_CASE_STATUS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Status '{candidate}' is not supported on claim stage",
                )
        else:
            # Pre-auth: existing business rule — once any approved amount
            # exists, fresh APPROVED becomes ENHANCEMENT_APPROVED, fresh DENIED
            # becomes ENHANCEMENT_DENIED.
            candidate = coerce_outcome_for_prior_approval(
                candidate, claim_case.approved_amount
            )

        applied_status = candidate

        # Write to the right column.
        if is_claim_stage:
            if applied_status != "UNKNOWN":
                claim_case.status = CLAIM_OUTCOME_TO_CASE_STATUS[applied_status]
            # Do NOT touch claim_case.claim_status / .approved_amount — those
            # are pre-auth state.
        else:
            claim_case.claim_status = applied_status

        # Auto-sync email_type from claim_status only if not explicitly provided.
        type_map = CLAIM_STATUS_TO_EMAIL_TYPE if is_claim_stage else STATUS_TO_EMAIL_TYPE
        if payload.email_type is None and applied_status in type_map:
            email_record.email_type = type_map[applied_status]

        # Resolve open query logs on a terminal outcome (approved/partial/denied).
        # Pre-auth includes enhancement terminals too.
        terminal_outcomes = {"APPROVED", "PARTIALLY_APPROVED", "DENIED"}
        if not is_claim_stage:
            terminal_outcomes |= {"ENHANCEMENT_APPROVED", "ENHANCEMENT_DENIED"}
        if applied_status in terminal_outcomes:
            open_queries = (
                db.query(QueryLog)
                .filter(QueryLog.claim_case_id == claim_case.id, QueryLog.status == "OPEN")
                .all()
            )
            for q in open_queries:
                q.status = "RESOLVED"
                q.resolved_at = datetime.now(timezone.utc)

    # Update claim_number. On claim stage we also mirror onto the claims row.
    if payload.claim_number is not None:
        claim_case.claim_number = payload.claim_number

    # `effective_status` is the bare outcome we should reason about for the
    # amount-handling block — newly applied if the caller changed it, else the
    # last known status on whichever column owns it for this stage.
    if applied_status is not None:
        effective_status = applied_status
    elif is_claim_stage:
        # Reverse-map claim_case.status (CLAIM_*) back to the bare form.
        effective_status = None
        for bare, prefixed in CLAIM_OUTCOME_TO_CASE_STATUS.items():
            if claim_case.status == prefixed:
                effective_status = bare
                break
    else:
        effective_status = claim_case.claim_status

    # The amount approved in THIS round — recorded on the StatusHistory row
    # below (mirrors the provider-action / validate-suggestion behaviour).
    status_history_amount = None
    explicit_amount_sent = (
        "approved_amount" in payload.model_fields_set
        and payload.approved_amount is not None
    )
    explicit_amount = None
    if explicit_amount_sent:
        try:
            explicit_amount = float(payload.approved_amount)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="approved_amount must be a number",
            )
        if explicit_amount < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="approved_amount cannot be negative",
            )

    _APPROVAL_STATUSES = ("APPROVED", "PARTIALLY_APPROVED", "ENHANCEMENT_APPROVED")
    if is_claim_stage:
        # Claim stage: settlement is single-shot. Write to the `claims` row
        # (status / approved_amount / processed_at). Leave claim_case pre-auth
        # totals untouched. `validation_status` on the email guards against
        # re-applying the same row twice.
        already_applied = email_record.validation_status == "APPROVED"
        claim_row = (
            db.query(Claim).filter(Claim.claim_case_id == claim_case.id).first()
        )

        if applied_status in ("APPROVED", "PARTIALLY_APPROVED", "DENIED"):
            if not claim_row:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Claim row missing for this claim case",
                )
            claim_row.status = applied_status
            if claim_row.processed_at is None:
                claim_row.processed_at = datetime.now(timezone.utc)
            if payload.claim_number is not None:
                claim_row.claim_number = payload.claim_number

        if effective_status in ("APPROVED", "PARTIALLY_APPROVED"):
            if not already_applied:
                if explicit_amount_sent:
                    round_amount = explicit_amount
                elif email_record.ai_suggested_amount is not None:
                    round_amount = float(email_record.ai_suggested_amount)
                else:
                    round_amount = None
                if round_amount is not None and claim_row is not None:
                    claim_row.approved_amount = round_amount  # set, not cumulate
                    email_record.ai_suggested_amount = round_amount
                    status_history_amount = round_amount
                email_record.validation_status = "APPROVED"
            elif explicit_amount_sent and claim_row is not None:
                # Reviewer correction on an already-applied row → overwrite.
                claim_row.approved_amount = explicit_amount
                email_record.ai_suggested_amount = explicit_amount
                status_history_amount = explicit_amount
        elif effective_status == "DENIED" and not already_applied:
            email_record.validation_status = "APPROVED"
    else:
        # Pre-auth path — existing cumulative semantics, untouched.
        if effective_status in _APPROVAL_STATUSES:
            already_applied = email_record.validation_status == "APPROVED"
            prior_total = float(claim_case.approved_amount or 0)
            if not already_applied:
                if explicit_amount_sent:
                    round_amount = explicit_amount
                elif email_record.ai_suggested_amount is not None:
                    round_amount = float(email_record.ai_suggested_amount)
                else:
                    round_amount = None
                if round_amount is not None:
                    claim_case.approved_amount = prior_total + round_amount
                    email_record.ai_suggested_amount = round_amount
                    status_history_amount = round_amount
                email_record.validation_status = "APPROVED"
            elif explicit_amount_sent:
                # Re-editing an already-applied email with a corrected figure —
                # move the cumulative by the difference, not the whole amount.
                old_amount = float(email_record.ai_suggested_amount or 0)
                if explicit_amount != old_amount:
                    claim_case.approved_amount = prior_total + (explicit_amount - old_amount)
                    email_record.ai_suggested_amount = explicit_amount
                status_history_amount = explicit_amount
        # Non-approval status (ADR_NMI / DENIED / ENHANCEMENT_DENIED) → no
        # amount change. An explicit `approved_amount` is ignored in that case.

    # ADR-only: hospital reviewer can edit the documents the insurer asked for.
    # We always persist the edited list onto the email row (replacing the AI
    # suggestion). If the resulting status is ADR_NMI, also surface it as an
    # OPEN QueryLog so the downstream ADR-response form can render it as a
    # checklist. Works for both stages — uses `applied_status` / effective.
    if "documents_list" in payload.model_fields_set:
        cleaned_docs = [
            str(d).strip()
            for d in (payload.documents_list or [])
            if d is not None and str(d).strip()
        ]
        email_record.ai_documents_list = cleaned_docs or None

        is_adr = (effective_status == "ADR_NMI")
        if is_adr:
            existing_log = (
                db.query(QueryLog)
                .filter(
                    QueryLog.claim_case_id == claim_case.id,
                    QueryLog.query_type == "ADR_NMI",
                    QueryLog.status == "OPEN",
                )
                .order_by(QueryLog.created_at.desc())
                .first()
            )
            if existing_log:
                existing_log.documents_list = cleaned_docs
            else:
                db.add(QueryLog(
                    claim_case_id=claim_case.id,
                    query_type="ADR_NMI",
                    query_details=email_record.ai_query_details
                        or email_record.ai_summary
                        or email_record.body,
                    documents_requested=email_record.ai_documents_requested,
                    documents_list=cleaned_docs,
                    status="OPEN",
                ))

    # Add status history for audit (link to the inbound email that was edited).
    # `status` is the bare outcome (matches what the provider-action and
    # validate-suggestion paths record). `stage` reflects current_stage so
    # claim-stage edits land on a CLAIM row in history.
    history_status = applied_status or effective_status or "UNKNOWN"
    user_remark = payload.remarks.strip() if payload.remarks and payload.remarks.strip() else None
    db.add(StatusHistory(
        claim_case_id=claim_case.id,
        stage=claim_case.current_stage,
        status=history_status,
        remarks=user_remark or "Manual edit of AI-extracted data",
        approved_amount=status_history_amount,
        email_id=email_id,
        changed_by="MANUAL_EDIT",
        updated_by=user_id,
    ))

    db.commit()
    db.refresh(claim_case)
    return claim_case
