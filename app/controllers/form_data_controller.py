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


def create_form_data(db: Session, payload: FormDataCreate) -> FormData:
    # Pre-auth content lives in the typed pre_auth_* tables.
    form_data = FormData(
        claim_case_id=payload.claim_case_id,
        stage="PRE_AUTH",
        draft_state="DRAFT",
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

    if form_data.draft_state == "SUBMITTED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit a submitted form",
        )

    # Per-section column update (only sections present in the payload change).
    apply_sections(db, form_data, payload.sections)
    db.commit()
    db.refresh(form_data)
    return form_data


def submit_form_data(db: Session, form_data_id: int) -> FormData:
    form_data = db.query(FormData).filter(FormData.id == form_data_id).first()
    if not form_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Form data not found",
        )

    if form_data.draft_state == "SUBMITTED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Form already submitted",
        )

    form_data.draft_state = "SUBMITTED"
    db.commit()
    db.refresh(form_data)
    return form_data


def create_claim_and_form_data(
    db: Session,
    payload: ClaimCaseSubmitForm,
    hospital_id=None,
    files: list[UploadFile] | None = None,
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
        stage="PRE_AUTH",
        draft_state="DRAFT",
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

    db.commit()
    db.refresh(claim_case)
    db.refresh(form_data)

    return {
        "claim_case_id": claim_case.id,
        "form_data_id": form_data.id,
        "status": claim_case.case_status,
    }
