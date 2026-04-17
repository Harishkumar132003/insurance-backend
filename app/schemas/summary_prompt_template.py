from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SummaryPromptTemplateUpdate(BaseModel):
    prompt_text: str


class SummaryPromptTemplateResponse(BaseModel):
    id: UUID
    key: str
    prompt_text: str
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}

