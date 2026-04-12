from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.hospital import Hospital
from app.schemas.hospital import HospitalCreate


def get_all_hospitals(db: Session):
    return db.query(Hospital).all()


def create_hospital(db: Session, payload: HospitalCreate):
    hospital = Hospital(
        name=payload.name,
        address=payload.address,
        rohini_id=payload.rohini_id,
        email=payload.email,
    )
    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    return hospital


def get_hospital(db: Session, hospital_id):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hospital not found",
        )
    return hospital
