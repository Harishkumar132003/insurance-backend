from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.policy_provider_config import PolicyProviderConfig
from app.schemas.policy_provider_config import PolicyProviderCreate, PolicyProviderUpdate


def create_provider(db: Session, payload: PolicyProviderCreate):
    config_data = {
        "auth": payload.auth.model_dump() if payload.auth else None,
        "steps": [s.model_dump() for s in payload.steps],
        "required_fields": payload.required_fields,
    }
    provider = PolicyProviderConfig(
        provider_id=payload.provider_id,
        name=payload.name,
        email=payload.email,
        tpa_name=payload.tpa_name,
        tpa_toll_free_phone=payload.tpa_toll_free_phone,
        tpa_toll_free_fax=payload.tpa_toll_free_fax,
        config=config_data,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


def get_provider_by_provider_id(db: Session, provider_id: str):
    provider = db.query(PolicyProviderConfig).filter(PolicyProviderConfig.provider_id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy provider not found")
    return provider


def get_all_providers(db: Session):
    return db.query(PolicyProviderConfig).all()


def get_provider(db: Session, provider_id: UUID):
    provider = db.query(PolicyProviderConfig).filter(PolicyProviderConfig.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy provider not found")
    return provider


def update_provider(db: Session, provider_id: UUID, payload: PolicyProviderUpdate):
    provider = get_provider(db, provider_id)
    if payload.provider_id is not None:
        provider.provider_id = payload.provider_id
    if payload.name is not None:
        provider.name = payload.name
    if payload.tpa_name is not None:
        provider.tpa_name = payload.tpa_name
    if payload.tpa_toll_free_phone is not None:
        provider.tpa_toll_free_phone = payload.tpa_toll_free_phone
    if payload.tpa_toll_free_fax is not None:
        provider.tpa_toll_free_fax = payload.tpa_toll_free_fax
    config = provider.config.copy()
    if payload.auth is not None:
        config["auth"] = payload.auth.model_dump()
    if payload.steps is not None:
        config["steps"] = [s.model_dump() for s in payload.steps]
    if payload.required_fields is not None:
        config["required_fields"] = payload.required_fields
    provider.config = config
    flag_modified(provider, "config")
    db.commit()
    db.refresh(provider)
    return provider


def delete_provider(db: Session, provider_id: UUID):
    provider = get_provider(db, provider_id)
    db.delete(provider)
    db.commit()
    return {"detail": "Policy provider deleted"}
