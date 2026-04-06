from datetime import datetime

from pydantic import BaseModel


class EmailTemplateCreate(BaseModel):
    name: str
    subject: str
    body: str


class EmailTemplateResponse(BaseModel):
    id: int
    name: str
    subject: str
    body: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
