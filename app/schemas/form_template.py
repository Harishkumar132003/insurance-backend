from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FormTemplateCreate(BaseModel):
    name: str
    version: int
    form_type: str = "PRE_AUTH"
    html_content: str | None = None
    policy_provider_id: UUID


class PolicyProviderInfo(BaseModel):
    id: UUID
    provider_id: str
    name: str

    model_config = {"from_attributes": True}


class FormTemplateResponse(BaseModel):
    id: int
    name: str
    version: int
    form_type: str
    policy_provider_id: UUID
    html_content: str | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class FormTemplateWithProviderResponse(BaseModel):
    id: int
    name: str
    version: int
    form_type: str
    policy_provider_id: UUID
    policy_provider: PolicyProviderInfo | None = None
    html_content: str | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
