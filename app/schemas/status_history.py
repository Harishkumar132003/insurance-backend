from datetime import datetime

from pydantic import BaseModel


class StatusHistoryCreate(BaseModel):
    claim_case_id: int
    stage: str
    status: str
    remarks: str | None = None
    changed_by: str | None = None


class StatusHistoryResponse(BaseModel):
    id: int
    claim_case_id: int
    stage: str
    status: str
    remarks: str | None = None
    changed_by: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
