import os
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.controllers import case_sheet_controller
from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.workflow import (
    CaseSheetExtractResponse,
    CaseSheetForCaseResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
    ContextSummaryRequest,
    ContextSummaryResponse,
)
from app.services.case_sheet_extraction_service import _is_image
from app.services.workflow_executor import execute_workflow, summarize_patient_policy_context
from app.utils.file_storage import get_attachment_full_path
from app.utils.signed_links import verify

router = APIRouter(tags=["Workflow"])


def _require_hospital(current_user: User):
    if not current_user.hospital_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user is not scoped to a hospital",
        )
    return current_user.hospital_id


@router.post("/run/{hospital_id}", response_model=WorkflowRunResponse)
async def run_workflow(
    hospital_id: UUID,
    payload: WorkflowRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await execute_workflow(db, hospital_id, payload.input)


@router.post("/extract-case-sheet", response_model=CaseSheetExtractResponse)
async def extract_case_sheet_route(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pull pre-auth form data out of a case sheet — one or more PDFs and/or photos
    of the pages. The alternative to the UHID workflow on the Fill-with-AI screen.

    The documents and the extraction (values, per-field confidence, provenance) are
    stored as an audit record; `case_sheet_id` comes back so the form can link it
    to the claim case on save. The form values themselves are still just a
    suggestion — the user reviews and edits everything before anything is saved to
    the pre-auth tables.
    """
    hospital_id = _require_hospital(current_user)
    uploads = [(await f.read(), f.filename, f.content_type) for f in files]
    # Off the event loop. extract_and_store blocks for the whole duration of the
    # OpenAI calls, and this process serves the signed public link that OpenAI
    # fetches the page images from — run it inline on the loop and the server
    # cannot answer that fetch, so the model times out downloading its own input.
    return await run_in_threadpool(
        case_sheet_controller.extract_and_store,
        db, hospital_id, current_user.id, uploads,
    )


@router.get("/case-sheets/by-claim-case/{claim_case_id}", response_model=CaseSheetForCaseResponse | None)
def case_sheet_for_claim_case(
    claim_case_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The case sheet a saved claim was pre-filled from, if any — so reopening the
    form can show the confidence chips and the source document again. Returns null
    for a case that wasn't built from a case sheet."""
    hospital_id = _require_hospital(current_user)
    return case_sheet_controller.get_for_claim_case(db, hospital_id, claim_case_id)


@router.get("/public/case-sheets/{case_sheet_id}/files/{index}")
def public_case_sheet_page(
    case_sheet_id: UUID,
    index: int,
    exp: int = Query(...),
    sig: str = Query(...),
    db: Session = Depends(get_db),
):
    """Case-sheet page image, fetchable WITHOUT a login.

    This exists so OpenAI's servers can download the image during extraction —
    they do not send an Authorization header. Access is gated on a short-lived
    HMAC signature instead of the session: no valid `exp`/`sig`, no file.

    Note this is patient data served without authentication. The signature and
    the expiry are the only controls; do not link to it from anywhere else.
    """
    if not verify(str(case_sheet_id), index, exp, sig):
        # Same response for expired, tampered and unknown — nothing to probe.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )
    ref = case_sheet_controller.get_file_ref_unscoped(db, case_sheet_id, index)
    # Images only. Nothing mints a link for a PDF — the model never needs one,
    # since PDFs are read locally — but state it here too, so the exposure stays
    # limited to images even if a signature for another index ever gets issued.
    if not _is_image(ref.get("original_filename"), ref.get("content_type")):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )
    return _serve(ref.get("file_path"), ref.get("content_type"), ref.get("original_filename"))


@router.get("/case-sheets/{case_sheet_id}/files/{index}")
def view_case_sheet_page(
    case_sheet_id: UUID,
    index: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serve one uploaded page inline — a PDF or a photo."""
    hospital_id = _require_hospital(current_user)
    ref = case_sheet_controller.get_file_ref(db, hospital_id, case_sheet_id, index)
    return _serve(ref.get("file_path"), ref.get("content_type"), ref.get("original_filename"))


@router.get("/case-sheets/{case_sheet_id}/file")
def view_case_sheet(
    case_sheet_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serve page 1 inline. Kept for callers that predate multi-page sheets."""
    hospital_id = _require_hospital(current_user)
    row = case_sheet_controller.get_for_file(db, hospital_id, case_sheet_id)
    return _serve(row.file_path, row.content_type, row.original_filename)


def _serve(file_path: str | None, content_type: str | None, filename: str | None):
    full_path = get_attachment_full_path(file_path) if file_path else None
    if not full_path or not os.path.exists(full_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk"
        )
    return FileResponse(
        path=full_path,
        media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{filename or "case-sheet"}"'},
    )


@router.post("/summarize-context", response_model=ContextSummaryResponse)
async def summarize_context(
    payload: ContextSummaryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await summarize_patient_policy_context(db, payload.patient, payload.policy)
