from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_super_admin
from app.controllers import summary_prompt_template_controller
from app.db.session import get_db
from app.models.user import User
from app.schemas.summary_prompt_template import (
    SummaryPromptTemplateResponse,
    SummaryPromptTemplateUpdate,
)

router = APIRouter(prefix="/summary-prompts", tags=["Summary Prompts"])


@router.get("", response_model=list[SummaryPromptTemplateResponse])
def list_summary_prompts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return summary_prompt_template_controller.get_all_prompts(db)


@router.get("/{key:path}", response_model=SummaryPromptTemplateResponse)
def get_summary_prompt(
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return summary_prompt_template_controller.get_prompt_by_key(db, key)


@router.put("/{key:path}", response_model=SummaryPromptTemplateResponse)
def update_summary_prompt(
    key: str,
    payload: SummaryPromptTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    return summary_prompt_template_controller.update_prompt_by_key(db, key, payload)
