from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.schemas.hospital_config import AuthConfig, StepConfig


class PolicyProviderCreate(BaseModel):
    provider_id: str
    name: str
    email: str | None = None
    auth: AuthConfig | None = None
    steps: list[StepConfig]
    required_fields: list[str] = []


class PolicyProviderUpdate(BaseModel):
    provider_id: str | None = None
    name: str | None = None
    auth: AuthConfig | None = None
    steps: list[StepConfig] | None = None
    required_fields: list[str] | None = None


class PolicyProviderResponse(BaseModel):
    id: UUID
    provider_id: str
    name: str
    email: str | None = None
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
