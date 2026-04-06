from datetime import datetime
from typing import Any

from pydantic import BaseModel


class FormDataCreate(BaseModel):
    claim_case_id: int | None = None
    data_json: dict[str, Any]


class FormDataUpdate(BaseModel):
    data_json: dict[str, Any]


class FormDataResponse(BaseModel):
    id: int
    status: str

    model_config = {"from_attributes": True}


class FormDataDetailResponse(BaseModel):
    id: int
    claim_case_id: int | None = None
    data_json: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
