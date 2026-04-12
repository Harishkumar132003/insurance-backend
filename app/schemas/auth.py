from typing import Any

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class HospitalDetail(BaseModel):
    id: str
    name: str
    address: str | None = None
    rohini_id: str | None = None
    email: str | None = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    hospital: HospitalDetail | None = None
