from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class PreAuthCreate(BaseModel):
    claim_case_id: UUID
    form_data_id: int


class PreAuthResponse(BaseModel):
    id: int
    claim_case_id: UUID
    form_data_id: int
    status: str
    request_date: datetime | None = None
    response_date: datetime | None = None
    approved_amount: Decimal | None = None
    remarks: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
