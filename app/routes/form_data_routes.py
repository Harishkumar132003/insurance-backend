import json
from typing import List

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.form_data import FormDataCreate, FormDataUpdate, FormDataResponse
from app.schemas.claim_case import ClaimCaseSubmitForm, ClaimCaseSubmitFormResponse
from app.controllers import form_data_controller

router = APIRouter(prefix="/form-data", tags=["Form Data"])


@router.post("/submit-form", response_model=ClaimCaseSubmitFormResponse, status_code=201)
async def submit_form(
    uhid: str = Form(...),
    policy_provider_id: str = Form(...),
    data_json: str = Form(...),
    files: List[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = ClaimCaseSubmitForm(
        uhid=uhid,
        policy_provider_id=policy_provider_id,
        data_json=json.loads(data_json),
    )
    return form_data_controller.create_claim_and_form_data(
        db, payload, hospital_id=current_user.hospital_id, files=files or [],
    )


@router.post("", response_model=FormDataResponse, status_code=201)
def create_form_data(
    payload: FormDataCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return form_data_controller.create_form_data(db, payload)


@router.patch("/{form_data_id}", response_model=FormDataResponse)
def update_form_data(
    form_data_id: int,
    payload: FormDataUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return form_data_controller.update_form_data(db, form_data_id, payload)


@router.post("/{form_data_id}/submit", response_model=FormDataResponse)
def submit_form_data(
    form_data_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return form_data_controller.submit_form_data(db, form_data_id)
