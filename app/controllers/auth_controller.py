from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import verify_password, create_access_token
from app.models.user import User
from app.schemas.auth import LoginRequest


def login(db: Session, payload: LoginRequest):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    access_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role,
        "hospital_id": str(user.hospital_id) if user.hospital_id else None,
    })
    response = {"access_token": access_token, "token_type": "bearer"}
    if user.role == "HOSPITAL_ADMIN" and user.hospital:
        response["hospital"] = {
            "id": str(user.hospital.id),
            "name": user.hospital.name,
            "address": user.hospital.address,
            "rohini_id": user.hospital.rohini_id,
            "email": user.hospital.email,
        }
    return response
