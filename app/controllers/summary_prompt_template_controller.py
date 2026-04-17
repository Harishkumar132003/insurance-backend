from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.summary_prompt_template import SummaryPromptTemplate
from app.schemas.summary_prompt_template import SummaryPromptTemplateUpdate


def get_all_prompts(db: Session):
    return db.query(SummaryPromptTemplate).order_by(SummaryPromptTemplate.key.asc()).all()


def get_prompt_by_key(db: Session, key: str):
    prompt = (
        db.query(SummaryPromptTemplate)
        .filter(SummaryPromptTemplate.key == key)
        .first()
    )
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template not found",
        )
    return prompt


def update_prompt_by_key(db: Session, key: str, payload: SummaryPromptTemplateUpdate):
    prompt = get_prompt_by_key(db, key)
    prompt.prompt_text = payload.prompt_text
    db.commit()
    db.refresh(prompt)
    return prompt
