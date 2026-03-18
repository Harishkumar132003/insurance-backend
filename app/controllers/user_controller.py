from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.models.hospital import Hospital
from app.schemas.user import UserCreate


def get_all_users(db: Session, hospital_id: str | None, current_user: User):
    query = db.query(User)
    if current_user.role == "HOSPITAL_ADMIN":
        query = query.filter(User.hospital_id == current_user.hospital_id)
    elif hospital_id:
        query = query.filter(User.hospital_id == hospital_id)
    return query.all()


def create_user(db: Session, payload: UserCreate):
    if payload.role not in ("SUPER_ADMIN", "HOSPITAL_ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be SUPER_ADMIN or HOSPITAL_ADMIN",
        )
    if payload.role == "HOSPITAL_ADMIN" and payload.hospital_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hospital_id is required for HOSPITAL_ADMIN",
        )
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
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
