from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FeatureCreate(BaseModel):
    key: str
    label: str | None = None
    is_active: bool = True


class FeatureUpdate(BaseModel):
    label: str | None = None
    is_active: bool | None = None


class FeatureResponse(BaseModel):
    id: UUID
    key: str
    label: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
