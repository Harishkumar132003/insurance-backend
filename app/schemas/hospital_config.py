from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator


class ResponseMapping(BaseModel):
    model_config = {"extra": "allow"}


class AuthConfig(BaseModel):
    type: str
    url: str
    method: str
    body: dict[str, Any] = {}
    response_mapping: dict[str, str] = {}


class StepConfig(BaseModel):
    step: str
    url: str
    method: str
    headers: dict[str, str] = {}
    body_template: dict[str, Any] = {}
    response_mapping: dict[str, str] = {}


class HospitalConfigCreate(BaseModel):
    auth: AuthConfig | None = None
    steps: list[StepConfig]
    required_fields: list[str]

    @model_validator(mode="after")
    def validate_steps_not_empty(self):
        if not self.steps:
            raise ValueError("steps must contain at least one step")
        return self


class HospitalConfigResponse(BaseModel):
    id: UUID
    hospital_id: UUID
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
