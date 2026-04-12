from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HospitalCreate(BaseModel):
    name: str
    address: str | None = None
    rohini_id: str | None = None
    email: str | None = None


class HospitalResponse(BaseModel):
    id: UUID
    name: str
    address: str | None = None
    rohini_id: str | None = None
    email: str | None = None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
