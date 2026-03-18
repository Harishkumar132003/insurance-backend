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
    provider = PolicyProviderConfig(name=payload.name, config=config_data)
    db.add(provider)
    db.commit()
    db.refresh(provider)
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
    if payload.name is not None:
        provider.name = payload.name
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
