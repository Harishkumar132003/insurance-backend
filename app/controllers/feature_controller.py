from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.feature import Feature
from app.schemas.feature import FeatureCreate, FeatureUpdate


def list_features(db: Session, active_only: bool = False) -> list[Feature]:
    query = db.query(Feature)
    if active_only:
        query = query.filter(Feature.is_active.is_(True))
    return query.order_by(Feature.key).all()


def create_feature(db: Session, payload: FeatureCreate) -> Feature:
    existing = db.query(Feature).filter(Feature.key == payload.key).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Feature key '{payload.key}' already exists",
        )
    feature = Feature(
        key=payload.key,
        label=payload.label,
        is_active=payload.is_active,
    )
    db.add(feature)
    db.commit()
    db.refresh(feature)
    return feature


def update_feature(db: Session, feature_id: UUID, payload: FeatureUpdate) -> Feature:
    feature = db.query(Feature).filter(Feature.id == feature_id).first()
    if not feature:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature not found"
        )
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(feature, field, value)
    db.commit()
    db.refresh(feature)
    return feature


def delete_feature(db: Session, feature_id: UUID) -> None:
    feature = db.query(Feature).filter(Feature.id == feature_id).first()
    if not feature:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature not found"
        )
    db.delete(feature)
    db.commit()
