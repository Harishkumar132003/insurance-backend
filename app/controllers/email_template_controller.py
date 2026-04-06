from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.email_template import EmailTemplate
from app.schemas.email_template import EmailTemplateCreate


def create_email_template(db: Session, payload: EmailTemplateCreate) -> EmailTemplate:
    template = EmailTemplate(
        name=payload.name,
        subject=payload.subject,
        body=payload.body,
        is_active=True,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def get_all_email_templates(db: Session) -> list[EmailTemplate]:
    return db.query(EmailTemplate).filter(EmailTemplate.is_active == True).all()


def get_email_template(db: Session, template_id: int) -> EmailTemplate:
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email template not found",
        )
    return template
