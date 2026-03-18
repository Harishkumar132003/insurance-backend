from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str  # SUPER_ADMIN or HOSPITAL_ADMIN
    hospital_id: UUID | None = None


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: str
    hospital_id: UUID | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
