from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class SettlementCreate(BaseModel):
    claim_id: int
    settled_amount: Decimal


class SettlementResponse(BaseModel):
    id: int
    claim_id: int
    settled_amount: Decimal
    status: str
    settlement_date: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
