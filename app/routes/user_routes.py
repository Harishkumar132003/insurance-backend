from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_hospital_admin
from app.controllers import feature_controller, user_controller
from app.models.user import User
from app.schemas.feature import FeatureResponse
from app.schemas.user import UserAccessUpdate, UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=list[UserResponse])
def list_users(
    hospital_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return user_controller.get_all_users(db, hospital_id, current_user)


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    return user_controller.create_user(db, payload, current_user)


@router.get("/features", response_model=list[FeatureResponse])
def list_feature_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Alias of GET /features — kept for frontend backwards compatibility."""
    return feature_controller.list_features(db, active_only=True)


@router.patch("/{user_id}/access", response_model=UserResponse)
def update_user_access(
    user_id: UUID,
    payload: UserAccessUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_hospital_admin),
):
    return user_controller.update_user_access(db, user_id, payload.access, current_user)
