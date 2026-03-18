from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.hospital import Hospital
from app.models.hospital_prompt import HospitalPrompt
from app.models.user import User
from app.schemas.hospital_prompt import HospitalPromptCreate, HospitalPromptUpdate


def _check_hospital_access(db: Session, hospital_id: UUID, current_user: User):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hospital not found")
    if current_user.role == "HOSPITAL_ADMIN" and current_user.hospital_id != hospital_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return hospital


def create_prompt(db: Session, hospital_id: UUID, payload: HospitalPromptCreate, current_user: User):
    _check_hospital_access(db, hospital_id, current_user)
    prompt = HospitalPrompt(
        hospital_id=hospital_id,
        name=payload.name,
        prompt_text=payload.prompt_text,
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


def get_all_prompts(db: Session, hospital_id: UUID, current_user: User):
    _check_hospital_access(db, hospital_id, current_user)
    return db.query(HospitalPrompt).filter(HospitalPrompt.hospital_id == hospital_id).all()


def get_prompt(db: Session, hospital_id: UUID, prompt_id: UUID, current_user: User):
    _check_hospital_access(db, hospital_id, current_user)
    prompt = (
        db.query(HospitalPrompt)
        .filter(HospitalPrompt.id == prompt_id, HospitalPrompt.hospital_id == hospital_id)
        .first()
    )
    if not prompt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    return prompt


def update_prompt(db: Session, hospital_id: UUID, prompt_id: UUID, payload: HospitalPromptUpdate, current_user: User):
    prompt = get_prompt(db, hospital_id, prompt_id, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(prompt, field, value)
    db.commit()
    db.refresh(prompt)
    return prompt


def delete_prompt(db: Session, hospital_id: UUID, prompt_id: UUID, current_user: User):
    prompt = get_prompt(db, hospital_id, prompt_id, current_user)
    db.delete(prompt)
    db.commit()
    return {"detail": "Prompt deleted"}
