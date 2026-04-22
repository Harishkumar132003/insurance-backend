from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers import feature_controller
from app.core.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.feature import FeatureCreate, FeatureResponse, FeatureUpdate

router = APIRouter(prefix="/features", tags=["Features"])


@router.get("", response_model=list[FeatureResponse])
def list_features(
    active_only: bool = Query(default=False, description="Return only active features"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return feature_controller.list_features(db, active_only=active_only)


@router.post("", response_model=FeatureResponse, status_code=201)
def create_feature(
    payload: FeatureCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    return feature_controller.create_feature(db, payload)


@router.patch("/{feature_id}", response_model=FeatureResponse)
def update_feature(
    feature_id: UUID,
    payload: FeatureUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    return feature_controller.update_feature(db, feature_id, payload)


@router.delete("/{feature_id}", status_code=204)
def delete_feature(
    feature_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    feature_controller.delete_feature(db, feature_id)
