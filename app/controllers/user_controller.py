from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.features import validate_access
from app.core.security import hash_password
from app.models.user import User
from app.models.hospital import Hospital
from app.models.policy_provider_config import PolicyProviderConfig
from app.schemas.user import UserCreate


def get_all_users(
    db: Session,
    hospital_id: str | None,
    current_user: User,
    role: str | None = None,
):
    query = db.query(User).options(joinedload(User.policy_provider))
    if current_user.role == "HOSPITAL_ADMIN":
        query = query.filter(User.hospital_id == current_user.hospital_id)
    elif hospital_id:
        query = query.filter(User.hospital_id == hospital_id)
    if role:
        query = query.filter(User.role == role)
    return query.all()


def create_user(db: Session, payload: UserCreate, current_user: User):
    if payload.role not in ("SUPER_ADMIN", "HOSPITAL_ADMIN", "INSURANCE_PROVIDER"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be SUPER_ADMIN, HOSPITAL_ADMIN, or INSURANCE_PROVIDER",
        )

    # Only SUPER_ADMIN can create INSURANCE_PROVIDER users (they span hospitals).
    if payload.role == "INSURANCE_PROVIDER" and current_user.role != "SUPER_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only SUPER_ADMIN can create INSURANCE_PROVIDER users",
        )

    # HOSPITAL_ADMIN creators can only create HOSPITAL_ADMINs inside their own hospital.
    if current_user.role == "HOSPITAL_ADMIN":
        if payload.role == "SUPER_ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="HOSPITAL_ADMIN cannot create SUPER_ADMIN users",
            )
        if payload.hospital_id is not None and payload.hospital_id != current_user.hospital_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot create users for another hospital",
            )
        # Ignore any mismatched / missing hospital_id — force to the admin's hospital.
        payload.hospital_id = current_user.hospital_id

    if payload.role == "HOSPITAL_ADMIN" and payload.hospital_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hospital_id is required for HOSPITAL_ADMIN",
        )
    if payload.role == "INSURANCE_PROVIDER":
        if payload.policy_provider_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="policy_provider_id is required for INSURANCE_PROVIDER",
            )
        provider = (
            db.query(PolicyProviderConfig)
            .filter(PolicyProviderConfig.id == payload.policy_provider_id)
            .first()
        )
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Policy provider not found",
            )
        # Provider users have no hospital.
        payload.hospital_id = None
    else:
        payload.policy_provider_id = None

    if payload.hospital_id:
        hospital = db.query(Hospital).filter(Hospital.id == payload.hospital_id).first()
        if not hospital:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hospital not found",
            )
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        hospital_id=payload.hospital_id,
        policy_provider_id=payload.policy_provider_id,
        access=validate_access(db, payload.access) if payload.access is not None else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_access(
    db: Session,
    user_id: UUID,
    access: list[str] | None,
    current_user: User,
) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # A HOSPITAL_ADMIN can only manage users inside their own hospital.
    if current_user.role == "HOSPITAL_ADMIN":
        if user.hospital_id != current_user.hospital_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot manage users from other hospitals",
            )

    user.access = None if access is None else validate_access(db, access)
    db.commit()
    db.refresh(user)
    return user
