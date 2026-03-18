from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HospitalPromptCreate(BaseModel):
    name: str
    prompt_text: str


class HospitalPromptUpdate(BaseModel):
    name: str | None = None
    prompt_text: str | None = None


class HospitalPromptResponse(BaseModel):
    id: UUID
    hospital_id: UUID
    name: str
    prompt_text: str
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
