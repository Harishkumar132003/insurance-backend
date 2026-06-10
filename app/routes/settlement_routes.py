import os
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.controllers import settlement_batch_controller
from app.core.deps import require_hospital_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.settlement_batch import (
    SettlementBatchListItem,
    SettlementBatchResponse,
    SettlementExtractResponse,
    SettlementMatchRequest,
    SettlementMatchResult,
    SettlementSavePayload,
)
from app.utils.file_storage import get_attachment_full_path

router = APIRouter(prefix="/settlements", tags=["Settlements"])


def _require_hospital(current_user: User) -> UUID:
    if not current_user.hospital_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user is not scoped to a hospital",
        )
    return current_user.hospital_id


@router.post("/extract", response_model=SettlementExtractResponse)
async def extract_settlement(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    """Parse an uploaded settlement file (PDF/Excel/CSV) into editable header +
    line items, each annotated with whether its claim number matches an
    existing case. Nothing is saved — this is a preview for the user to correct."""
    hospital_id = _require_hospital(current_user)
    file_bytes = await file.read()
    return settlement_batch_controller.extract(db, hospital_id, file_bytes, file.filename, file.content_type)


@router.post("/match", response_model=list[SettlementMatchResult])
def match_claims(
    payload: SettlementMatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    """Re-check which claim numbers map to existing cases. Drives the live
    match badges on the review screen as the user edits claim numbers."""
    hospital_id = _require_hospital(current_user)
    return settlement_batch_controller.match_numbers(db, hospital_id, payload.claim_numbers)


@router.post("", response_model=SettlementBatchResponse, status_code=201)
def save_settlement(
    payload: SettlementSavePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    """Persist the reviewed settlement: saves the header + items, links the file
    stored at extract time, and maps each line to a claim case via claim_number."""
    hospital_id = _require_hospital(current_user)
    return settlement_batch_controller.save(db, hospital_id, payload)


@router.put("/{batch_id}", response_model=SettlementBatchResponse)
def update_settlement(
    batch_id: UUID,
    payload: SettlementSavePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    """Update a saved settlement's header + line items (re-maps claim numbers).
    The originally uploaded file is kept as-is."""
    hospital_id = _require_hospital(current_user)
    return settlement_batch_controller.update(db, hospital_id, batch_id, payload)


@router.get("", response_model=list[SettlementBatchListItem])
def list_settlements(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    hospital_id = _require_hospital(current_user)
    return settlement_batch_controller.list_batches(db, hospital_id)


@router.get("/{batch_id}", response_model=SettlementBatchResponse)
def get_settlement(
    batch_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    hospital_id = _require_hospital(current_user)
    return settlement_batch_controller.get_detail(db, hospital_id, batch_id)


@router.get("/{batch_id}/file")
def download_settlement_file(
    batch_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    hospital_id = _require_hospital(current_user)
    batch = settlement_batch_controller.get_batch(db, hospital_id, batch_id)
    if not batch.source_file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No file stored for this settlement.")
    full_path = get_attachment_full_path(batch.source_file_path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk.")
    return FileResponse(
        path=full_path,
        media_type=batch.source_content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{batch.source_original_filename or "settlement"}"'},
    )
