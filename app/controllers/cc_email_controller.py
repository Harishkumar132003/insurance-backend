from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.cc_email import CcEmail
from app.schemas.cc_email import CcEmailCreate, CcEmailUpdate


def create_cc_email(db: Session, payload: CcEmailCreate):
    cc = CcEmail(
        email=payload.email,
        hospital_id=payload.hospital_id,
        policy_provider_id=payload.policy_provider_id,
    )
    db.add(cc)
    db.commit()
    db.refresh(cc)
    return cc


def list_cc_emails_for_hospital(db: Session, hospital_id: UUID):
    return db.query(CcEmail).filter(CcEmail.hospital_id == hospital_id).all()


def list_cc_emails_for_provider(db: Session, provider_id: UUID):
    return db.query(CcEmail).filter(CcEmail.policy_provider_id == provider_id).all()


def update_cc_email(db: Session, cc_email_id: int, payload: CcEmailUpdate):
    cc = db.query(CcEmail).filter(CcEmail.id == cc_email_id).first()
    if not cc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CC email not found")
    cc.email = payload.email
    db.commit()
    db.refresh(cc)
    return cc


def delete_cc_email(db: Session, cc_email_id: int):
    cc = db.query(CcEmail).filter(CcEmail.id == cc_email_id).first()
    if not cc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CC email not found")
    db.delete(cc)
    db.commit()
    return {"detail": "CC email deleted"}
