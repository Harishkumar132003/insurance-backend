from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class FormDataCreate(BaseModel):
    claim_case_id: UUID | None = None
    # Nested pre-auth sections: {patient_insured, treating_doctor, hospitalization}
    sections: dict[str, Any]


class FormDataUpdate(BaseModel):
    sections: dict[str, Any]
    # Both live on the parent ClaimCase, not on the form row. Optional so a
    # partial update that omits them leaves them alone — without them here
    # Pydantic silently dropped the fields and edits to a draft's provider or
    # UHID were lost on save.
    uhid: str | None = None
    policy_provider_id: UUID | None = None


class FormDataResponse(BaseModel):
    id: int
    preauth_status: str

    model_config = {"from_attributes": True}


class FormDataDetailResponse(BaseModel):
    id: int
    claim_case_id: UUID | None = None
    sections: dict[str, Any] = {}
    preauth_status: str
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
