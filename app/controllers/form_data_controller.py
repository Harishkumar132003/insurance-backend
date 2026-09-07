from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models.claim_case import ClaimCase
from app.models.claim_case_document import ClaimCaseDocument
from app.models.form_data import FormData
from app.models.status_history import StatusHistory
from app.schemas.form_data import FormDataCreate, FormDataUpdate
from app.schemas.claim_case import ClaimCaseSubmitForm
from app.utils.file_storage import save_document
from app.utils.pre_auth_sections import apply_sections
from app.controllers import case_sheet_controller


def create_form_data(db: Session, payload: FormDataCreate) -> FormData:
    # Pre-auth content lives in the typed pre_auth_* tables.
    form_data = FormData(
        claim_case_id=payload.claim_case_id,
    )
    db.add(form_data)
    db.flush()
    apply_sections(db, form_data, payload.sections)
    db.commit()
    db.refresh(form_data)
    return form_data


def update_form_data(db: Session, form_data_id: int, payload: FormDataUpdate) -> FormData:
    form_data = db.query(FormData).filter(FormData.id == form_data_id).first()
    if not form_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Form data not found",
        )

    # A pre-auth form is "submitted" once the case leaves DRAFT (case_status is
    # mirrored onto preauth_status). Replaces the old draft_state flag.
    if form_data.preauth_status != "DRAFT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit a submitted form",
        )

    # Provider / UHID live on the parent case. Applied only when sent, so this
    # stays a partial update like apply_sections. Guarded by the SUBMITTED check
    # above, so a case already with the insurer can't be re-pointed mid-flight.
    claim_case = (
        db.query(ClaimCase).filter(ClaimCase.id == form_data.claim_case_id).first()
        if form_data.claim_case_id else None
    )
    if claim_case is not None:
        if payload.policy_provider_id is not None:
            claim_case.policy_provider_id = payload.policy_provider_id
        # The column is NOT NULL, so a blank must not overwrite a real UHID.
        if payload.uhid is not None and payload.uhid.strip():
            claim_case.uhid = payload.uhid.strip()

    # Per-section column update (only sections present in the payload change).
    apply_sections(db, form_data, payload.sections)
    db.commit()
    db.refresh(form_data)
    return form_data


def create_claim_and_form_data(
    db: Session,
    payload: ClaimCaseSubmitForm,
    hospital_id=None,
    files: list[UploadFile] | None = None,
    case_sheet_id=None,
) -> dict:
    # 1. Create ClaimCase with DRAFT status
    claim_case = ClaimCase(
        uhid=payload.uhid,
        policy_provider_id=payload.policy_provider_id,
        hospital_id=hospital_id,
        case_status="DRAFT",   # renamed from `status` (see ClaimCase model)
    )
    db.add(claim_case)
    db.flush()

    # 2. Create FormData linked to the ClaimCase + write the typed sections.
    form_data = FormData(
        claim_case_id=claim_case.id,
    )
    db.add(form_data)
    db.flush()
    apply_sections(db, form_data, payload.sections)

    # 3. Add initial status history entry
    db.add(StatusHistory(
        claim_case_id=claim_case.id,
        stage="PRE_AUTH",
        status="DRAFT",
        remarks="Pre-auth form drafted",
    ))

    # 4. Save uploaded documents
    for file in (files or []):
        file_bytes = file.file.read()
        original_filename = file.filename or "unnamed_file"
        stored_filename, file_path = save_document(claim_case.id, file_bytes, original_filename)
        db.add(ClaimCaseDocument(
            claim_case_id=claim_case.id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_path=file_path,
            content_type=file.content_type,
            file_size=len(file_bytes),
        ))

    # 5. If this form was pre-filled from a case sheet, attach that extraction to
    #    the case it produced. Best-effort — never fail an otherwise good submit.
    case_sheet_controller.link_to_claim_case(db, hospital_id, case_sheet_id, claim_case.id)

    db.commit()
    db.refresh(claim_case)
    db.refresh(form_data)

    return {
        "claim_case_id": claim_case.id,
        "form_data_id": form_data.id,
        "status": claim_case.case_status,
    }
