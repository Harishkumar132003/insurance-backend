import json
import os
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.controllers import hospital_provider_controller
from app.core.deps import require_hospital_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.hospital_provider import (
    HospitalProviderResponse,
    HospitalProviderUpdate,
    MouExtractResponse,
    MouUploadResponse,
    OnboardedProviderResponse,
)
from app.schemas.policy_provider_config import PolicyProviderResponse
from app.utils.file_storage import get_attachment_full_path

router = APIRouter(tags=["Hospital Providers"])


def _require_hospital(current_user: User):
    if not current_user.hospital_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user is not scoped to a hospital",
        )
    return current_user.hospital_id


@router.post("/hospital-providers/extract-mou", response_model=MouExtractResponse)
async def extract_mou(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    _require_hospital(current_user)
    file_bytes = await file.read()
    return hospital_provider_controller.extract_mou(
        file_bytes, file.filename, file.content_type
    )


@router.get("/hospital-providers", response_model=list[HospitalProviderResponse])
def list_hospital_providers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    hospital_id = _require_hospital(current_user)
    return hospital_provider_controller.list_for_hospital(db, hospital_id)


@router.get("/hospital-providers/providers", response_model=list[OnboardedProviderResponse])
def list_onboarded_providers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    hospital_id = _require_hospital(current_user)
    return hospital_provider_controller.list_onboarded_providers(db, hospital_id)


@router.get("/hospital-providers/available", response_model=list[PolicyProviderResponse])
def list_available_providers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    hospital_id = _require_hospital(current_user)
    return hospital_provider_controller.list_available_providers(db, hospital_id)


@router.post("/hospital-providers", response_model=HospitalProviderResponse, status_code=201)
async def create_hospital_provider(
    provider_name: str | None = Form(None),
    provider_external_id: str | None = Form(None),
    email: str | None = Form(None),
    tpa_name: str | None = Form(None),
    tpa_toll_free_phone: str | None = Form(None),
    tpa_toll_free_fax: str | None = Form(None),
    policy_provider_id: UUID | None = Form(None),
    room_charges: str | None = Form(None),
    extracted_data: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    hospital_id = _require_hospital(current_user)

    def _parse(raw: str | None, field: str):
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{field} must be valid JSON",
            )

    parsed_charges = _parse(room_charges, "room_charges")
    # The raw AI extraction the form previewed, kept for audit / re-edit.
    parsed_extracted = _parse(extracted_data, "extracted_data")

    mou_bytes = mou_filename = mou_content_type = None
    if file is not None:
        mou_bytes = await file.read()
        mou_filename = file.filename
        mou_content_type = file.content_type

    return hospital_provider_controller.create_mapping(
        db,
        hospital_id,
        provider_name=provider_name,
        provider_external_id=provider_external_id,
        email=email,
        tpa_name=tpa_name,
        tpa_toll_free_phone=tpa_toll_free_phone,
        tpa_toll_free_fax=tpa_toll_free_fax,
        room_charges=parsed_charges,
        mou_bytes=mou_bytes,
        mou_filename=mou_filename,
        mou_content_type=mou_content_type,
        existing_provider_id=policy_provider_id,
        extracted_data=parsed_extracted,
    )


@router.post("/hospital-providers/{mapping_id}/mou", response_model=MouUploadResponse)
async def upload_mou(
    mapping_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    """Attach or replace this mapping's MOU and re-run the tariff extraction.

    Returns the extracted charges for the admin to review — `room_charges` is left
    untouched, so the live tariffs only change when the follow-up update commits
    the reviewed values.
    """
    hospital_id = _require_hospital(current_user)
    file_bytes = await file.read()
    return hospital_provider_controller.replace_mou(
        db, hospital_id, mapping_id, file_bytes, file.filename, file.content_type
    )


@router.put("/hospital-providers/{mapping_id}", response_model=HospitalProviderResponse)
def update_hospital_provider(
    mapping_id: UUID,
    payload: HospitalProviderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    hospital_id = _require_hospital(current_user)
    return hospital_provider_controller.update_mapping(db, hospital_id, mapping_id, payload)


@router.get("/hospital-providers/{mapping_id}/mou")
def view_mou(
    mapping_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    hospital_id = _require_hospital(current_user)
    mapping = hospital_provider_controller.get_mapping_for_mou(db, hospital_id, mapping_id)
    full_path = get_attachment_full_path(mapping.mou_file_path)
    if not os.path.exists(full_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk"
        )
    return FileResponse(
        path=full_path,
        media_type=mapping.mou_content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{mapping.mou_original_filename}"'},
    )


@router.delete("/hospital-providers/{mapping_id}")
def delete_hospital_provider(
    mapping_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    hospital_id = _require_hospital(current_user)
    return hospital_provider_controller.delete_mapping(db, hospital_id, mapping_id)
