from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class QueryLogResponse(BaseModel):
    id: int
    claim_case_id: UUID
    query_type: str
    query_details: str | None = None
    documents_requested: str | None = None
    documents_list: list[str] | None = None
    status: str
    resolved_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
