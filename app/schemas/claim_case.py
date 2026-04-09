from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.schemas.claim_case_document import ClaimCaseDocumentResponse


class ClaimCaseCreate(BaseModel):
    uhid: str
    hospital_id: UUID | None = None
    policy_provider_id: UUID


class ClaimCaseResponse(BaseModel):
    id: UUID
    uhid: str
    hospital_id: UUID | None = None
    policy_provider_id: UUID
    claim_number: str | None = None
    thread_id: str | None = None
    current_stage: str
    status: str
    claim_status: str | None = None
    approved_amount: float | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class StatusHistoryItem(BaseModel):
    id: int
    stage: str
    status: str
    remarks: str | None = None
    changed_by: str | None = None
    updated_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FormDataItem(BaseModel):
    id: int
    data_json: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class QueryLogItem(BaseModel):
    id: int
    query_type: str
    query_details: str | None = None
    documents_requested: str | None = None
    status: str
    resolved_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClaimCaseDetailResponse(BaseModel):
    id: UUID
    uhid: str
    hospital_id: UUID | None = None
    policy_provider_id: UUID
    claim_number: str | None = None
    thread_id: str | None = None
    current_stage: str
    status: str
    claim_status: str | None = None
    approved_amount: float | None = None
    created_at: datetime
    updated_at: datetime | None = None
    form_data: list[FormDataItem] = []
    status_history: list[StatusHistoryItem] = []
    query_logs: list[QueryLogItem] = []
    emails: list["ClaimCaseEmailListItem"] = []
    documents: list[ClaimCaseDocumentResponse] = []

    model_config = {"from_attributes": True}


class ClaimCaseEmailListItem(BaseModel):
    id: int
    direction: str
    from_email: str
    to_email: str
    subject: str | None = None
    email_date: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClaimCaseStatusUpdate(BaseModel):
    status: str
    remarks: str | None = None


class ClaimCaseExtractedDataUpdate(BaseModel):
    claim_status: str | None = None
    claim_number: str | None = None
    approved_amount: float | None = None
    email_type: str | None = None


class ClaimCaseSubmitForm(BaseModel):
    uhid: str
    policy_provider_id: UUID
    data_json: dict[str, Any]


class ClaimCaseSubmitFormResponse(BaseModel):
    claim_case_id: UUID
    form_data_id: int
    status: str


class ClaimListItem(BaseModel):
    claim_case_id: UUID
    patient_name: str | None = None
    claim_number: str | None = None
    claim_status: str | None = None
    provider_name: str | None = None
    provider_id: str | None = None
    amount: float | None = None
    approved_amount: float | None = None
    status: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
