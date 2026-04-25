from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str  # SUPER_ADMIN, HOSPITAL_ADMIN, or INSURANCE_PROVIDER
    hospital_id: UUID | None = None
    policy_provider_id: UUID | None = None
    access: list[str] | None = None  # None = full access


class UserPolicyProviderInfo(BaseModel):
    id: UUID
    provider_id: str
    name: str
    email: str | None = None

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: str
    hospital_id: UUID | None
    policy_provider_id: UUID | None = None
    policy_provider: UserPolicyProviderInfo | None = None
    access: list[str] | None = None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class UserAccessUpdate(BaseModel):
    access: list[str] | None  # None = full access, [] = none, list = allow-list
