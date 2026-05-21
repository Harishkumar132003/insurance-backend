from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class RoomCharge(BaseModel):
    room: str
    per_day_rent: float | None = None


class RoomChargesData(BaseModel):
    room_type: list[RoomCharge] = []
    icu: float | None = None
    ot_charge: float | None = None


class MouExtractResponse(BaseModel):
    room_type: list[RoomCharge] = []
    icu: float | None = None
    ot_charge: float | None = None


class HospitalProviderResponse(BaseModel):
    id: UUID
    hospital_id: UUID
    policy_provider_id: UUID
    provider_name: str
    provider_external_id: str | None = None
    email: str | None = None
    tpa_name: str | None = None
    tpa_toll_free_phone: str | None = None
    tpa_toll_free_fax: str | None = None
    room_charges: dict[str, Any] | None = None
    mou_original_filename: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime | None = None


class OnboardedProviderResponse(BaseModel):
    """Provider config + this hospital's MOU room charges — feeds the pre-auth
    provider selector and its dependent Room Type dropdown."""
    id: UUID
    provider_id: str | None = None
    name: str
    email: str | None = None
    tpa_name: str | None = None
    tpa_toll_free_phone: str | None = None
    tpa_toll_free_fax: str | None = None
    room_charges: dict[str, Any] | None = None


class HospitalProviderUpdate(BaseModel):
    provider_name: str | None = None
    email: str | None = None
    tpa_name: str | None = None
    tpa_toll_free_phone: str | None = None
    tpa_toll_free_fax: str | None = None
    room_charges: RoomChargesData | None = None
    is_active: bool | None = None
