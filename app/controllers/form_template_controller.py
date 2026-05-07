from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.form_template import FormTemplate
from app.schemas.form_template import FormTemplateCreate


def create_form_template(db: Session, payload: FormTemplateCreate) -> FormTemplate:
    existing = (
        db.query(FormTemplate)
        .filter(
            FormTemplate.name == payload.name,
            FormTemplate.version == payload.version,
            FormTemplate.form_type == payload.form_type,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Form template '{payload.name}' version {payload.version} ({payload.form_type}) already exists",
        )

    template = FormTemplate(
        name=payload.name,
        version=payload.version,
        form_type=payload.form_type,
        policy_provider_id=payload.policy_provider_id,
        html_content=payload.html_content,
        is_active=True,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def get_form_template_by_id(db: Session, template_id: int) -> FormTemplate:
    template = db.query(FormTemplate).filter(FormTemplate.id == template_id).first()
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Form template not found",
        )
    return template


def get_first_form_template(db: Session, form_type: str | None = None) -> FormTemplate:
    query = db.query(FormTemplate).filter(FormTemplate.is_active == True)
    if form_type:
        query = query.filter(FormTemplate.form_type == form_type)
    template = query.order_by(FormTemplate.id.asc()).first()
    if not template:
        detail = (
            f"No active {form_type} form template found"
            if form_type else "No active form template found"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
        )
    return template


def get_all_form_templates(db: Session, form_type: str | None = None):
    query = db.query(FormTemplate)
    if form_type:
        query = query.filter(FormTemplate.form_type == form_type)
    return query.all()


def get_form_template_by_provider(
    db: Session, policy_provider_id, form_type: str = "PRE_AUTH"
) -> FormTemplate:
    template = (
        db.query(FormTemplate)
        .filter(
            FormTemplate.policy_provider_id == policy_provider_id,
            FormTemplate.form_type == form_type,
            FormTemplate.is_active == True,
        )
        .order_by(FormTemplate.version.desc())
        .first()
    )
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active {form_type} form template found for this policy provider",
        )
    return template
