from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.secrets import encrypt_hospital_password
from app.models.hospital import Hospital
from app.schemas.hospital import HospitalCreate, HospitalUpdate


def _attach_flag(hospital: Hospital) -> Hospital:
    # Never expose the ciphertext; surface only a presence flag.
    hospital.has_app_password = bool(hospital.app_password)
    return hospital


def get_all_hospitals(db: Session):
    return [_attach_flag(h) for h in db.query(Hospital).all()]


def create_hospital(db: Session, payload: HospitalCreate):
    app_password_ciphertext = None
    if payload.app_password:
        if not payload.rohini_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="rohini_id is required to store an app_password",
            )
        app_password_ciphertext = encrypt_hospital_password(
            payload.app_password, payload.rohini_id
        )

    hospital = Hospital(
        name=payload.name,
        address=payload.address,
        rohini_id=payload.rohini_id,
        email=payload.email,
        app_password=app_password_ciphertext,
    )
    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    return _attach_flag(hospital)


def update_hospital(db: Session, hospital_id, payload: HospitalUpdate):
    hospital = get_hospital(db, hospital_id)
    data = payload.model_dump(exclude_unset=True)

    # Reject rohini_id changes when a password is stored — the ciphertext is
    # bound to the current rohini_id and would become undecryptable.
    if (
        "rohini_id" in data
        and data["rohini_id"] != hospital.rohini_id
        and hospital.app_password
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot change rohini_id while an app_password is stored. "
                "Clear the app_password first (send \"app_password\": \"\"), "
                "update rohini_id, then re-supply the password."
            ),
        )

    if "app_password" in data:
        plaintext = data.pop("app_password")
        if plaintext in (None, ""):
            hospital.app_password = None
        else:
            rohini = data.get("rohini_id", hospital.rohini_id)
            if not rohini:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="rohini_id is required to store an app_password",
                )
            hospital.app_password = encrypt_hospital_password(plaintext, rohini)

    for field, value in data.items():
        setattr(hospital, field, value)

    db.commit()
    db.refresh(hospital)
    return _attach_flag(hospital)


def get_hospital(db: Session, hospital_id):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found",
        )
    return _attach_flag(hospital)
