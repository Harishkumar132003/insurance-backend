from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.form_template import FormTemplate
from app.schemas.form_template import FormTemplateCreate


def create_form_template(db: Session, payload: FormTemplateCreate) -> FormTemplate:
    existing = (
        db.query(FormTemplate)
        .filter(FormTemplate.name == payload.name, FormTemplate.version == payload.version)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Form template '{payload.name}' version {payload.version} already exists",
        )

    template = FormTemplate(
        name=payload.name,
        version=payload.version,
        policy_provider_id=payload.policy_provider_id,
        schema_json=payload.schema_json,
        is_active=True,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def get_first_form_template(db: Session) -> FormTemplate:
    template = (
        db.query(FormTemplate)
        .filter(FormTemplate.is_active == True)
        .order_by(FormTemplate.id.asc())
        .first()
    )
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active form template found",
        )
    return template


def get_form_template_by_provider(db: Session, policy_provider_id) -> FormTemplate:
    template = (
        db.query(FormTemplate)
        .filter(
            FormTemplate.policy_provider_id == policy_provider_id,
            FormTemplate.is_active == True,
        )
        .order_by(FormTemplate.version.desc())
        .first()
    )
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active form template found for this policy provider",
        )
    return template
