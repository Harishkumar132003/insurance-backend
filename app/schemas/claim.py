from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ClaimCreate(BaseModel):
    claim_case_id: int
    claimed_amount: Decimal


class ClaimResponse(BaseModel):
    id: int
    claim_case_id: int
    claimed_amount: Decimal
    approved_amount: Decimal | None = None
    status: str
    submitted_at: datetime | None = None
    processed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
