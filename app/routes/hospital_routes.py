from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_super_admin
from app.models.user import User
from app.schemas.hospital import HospitalCreate, HospitalResponse
from app.controllers import hospital_controller

router = APIRouter(prefix="/hospitals", tags=["Hospitals"])


@router.get("", response_model=list[HospitalResponse])
def list_hospitals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return hospital_controller.get_all_hospitals(db)


@router.post("", response_model=HospitalResponse, status_code=201)
def create_hospital(
    payload: HospitalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    return hospital_controller.create_hospital(db, payload)
