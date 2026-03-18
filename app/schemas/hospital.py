from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HospitalCreate(BaseModel):
    name: str


class HospitalResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
