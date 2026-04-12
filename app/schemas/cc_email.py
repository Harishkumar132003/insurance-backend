from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class CcEmailCreate(BaseModel):
    email: EmailStr
    hospital_id: UUID | None = None
    policy_provider_id: UUID | None = None


class CcEmailUpdate(BaseModel):
    email: EmailStr


class CcEmailResponse(BaseModel):
    id: int
    email: str
    hospital_id: UUID | None = None
    policy_provider_id: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
