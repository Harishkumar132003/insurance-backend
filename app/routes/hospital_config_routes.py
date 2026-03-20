from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.hospital_config import HospitalConfigCreate, HospitalConfigResponse, GlobalVariableUpdate, GlobalVariableResponse
from app.controllers import hospital_config_controller

router = APIRouter(prefix="/hospitals", tags=["Hospital Config"])


@router.post(
    "/{hospital_id}/config",
    response_model=HospitalConfigResponse,
    status_code=201,
)
def create_or_update_config(
    hospital_id: UUID,
    payload: HospitalConfigCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return hospital_config_controller.create_or_update_config(
        db, hospital_id, payload, current_user
    )


@router.get(
    "/{hospital_id}/config",
    response_model=HospitalConfigResponse,
)
def get_config(
    hospital_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return hospital_config_controller.get_config(db, hospital_id, current_user)


@router.get(
    "/{hospital_id}/config/variables",
    response_model=GlobalVariableResponse,
)
def get_global_variables(
    hospital_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return hospital_config_controller.get_global_variables(db, hospital_id, current_user)


@router.put(
    "/{hospital_id}/config/variables",
    response_model=GlobalVariableResponse,
)
def update_global_variables(
    hospital_id: UUID,
    payload: GlobalVariableUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return hospital_config_controller.update_global_variables(db, hospital_id, payload.variables, current_user)


@router.delete("/{hospital_id}/config/variables/{key}", response_model=GlobalVariableResponse)
def delete_global_variable(
    hospital_id: UUID,
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return hospital_config_controller.delete_global_variable(db, hospital_id, key, current_user)
