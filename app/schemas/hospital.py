from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HospitalCreate(BaseModel):
    name: str
    address: str | None = None
    rohini_id: str | None = None
    email: str | None = None
    app_password: str | None = None  # plaintext in; encrypted before storage


class HospitalUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    rohini_id: str | None = None
    email: str | None = None
    app_password: str | None = None  # plaintext in; "" clears the stored value


class HospitalResponse(BaseModel):
    id: UUID
    name: str
    address: str | None = None
    rohini_id: str | None = None
    email: str | None = None
    has_app_password: bool = False  # populated by controller; ciphertext itself is never returned
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
