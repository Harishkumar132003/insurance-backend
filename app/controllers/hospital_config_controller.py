from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.hospital import Hospital
from app.models.hospital_config import HospitalConfig
from app.models.user import User
from sqlalchemy.orm.attributes import flag_modified

from app.schemas.hospital_config import HospitalConfigCreate


def create_or_update_config(
    db: Session, hospital_id: UUID, payload: HospitalConfigCreate, current_user: User
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found",
        )
    if current_user.role == "HOSPITAL_ADMIN" and current_user.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage config for your own hospital",
        )

    config_data = payload.model_dump()

    existing = (
        db.query(HospitalConfig)
        .filter(HospitalConfig.hospital_id == hospital_id)
        .first()
    )
    if existing:
        existing.config = config_data
        db.commit()
        db.refresh(existing)
        return existing

    config = HospitalConfig(hospital_id=hospital_id, config=config_data)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def get_config(db: Session, hospital_id: UUID, current_user: User):
    if current_user.role == "HOSPITAL_ADMIN" and current_user.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access config for your own hospital",
        )
    config = (
        db.query(HospitalConfig)
        .filter(HospitalConfig.hospital_id == hospital_id)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Config not found for this hospital",
        )
    return config


def _get_config_or_404(db: Session, hospital_id: UUID, current_user: User):
    if current_user.role == "HOSPITAL_ADMIN" and current_user.hospital_id != hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    config = (
        db.query(HospitalConfig)
        .filter(HospitalConfig.hospital_id == hospital_id)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Config not found for this hospital",
        )
    return config


def get_global_variables(db: Session, hospital_id: UUID, current_user: User):
    config = _get_config_or_404(db, hospital_id, current_user)
    return {"hospital_id": hospital_id, "global_variables": config.global_variables or {}}


def update_global_variables(db: Session, hospital_id: UUID, variables: dict, current_user: User):
    config = _get_config_or_404(db, hospital_id, current_user)
    config.global_variables = variables
    flag_modified(config, "global_variables")
    db.commit()
    db.refresh(config)
    return {"hospital_id": hospital_id, "global_variables": config.global_variables}


def delete_global_variable(db: Session, hospital_id: UUID, key: str, current_user: User):
    config = _get_config_or_404(db, hospital_id, current_user)
    variables = config.global_variables or {}
    if key not in variables:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Variable '{key}' not found",
        )
    del variables[key]
    config.global_variables = variables
    flag_modified(config, "global_variables")
    db.commit()
    db.refresh(config)
    return {"hospital_id": hospital_id, "global_variables": config.global_variables}
