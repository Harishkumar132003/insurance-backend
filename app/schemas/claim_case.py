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
    approved_amount: float | None = None  # per-round amount (not cumulative)
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
    documents_list: list[str] | None = None
    status: str
    resolved_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClaimCaseSummary(BaseModel):
    patient_name: str | None = None
    uhid: str | None = None
    provider_name: str | None = None
    diagnosis: str | None = None
    icd_10: str | None = None
    requested_amount: float | None = None


class ClaimCaseHeaderInfo(BaseModel):
    tpa_name: str | None = None
    tpa_toll_free_phone: str | None = None
    tpa_toll_free_fax: str | None = None
    hospital_name: str | None = None
    hospital_address: str | None = None
    hospital_rohini_id: str | None = None
    hospital_email: str | None = None


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
    summary: ClaimCaseSummary | None = None
    header_info: ClaimCaseHeaderInfo | None = None
    form_data: list[FormDataItem] = []
    status_history: list[StatusHistoryItem] = []
    query_logs: list[QueryLogItem] = []
    emails: list["ClaimCaseEmailListItem"] = []
    documents: list[ClaimCaseDocumentResponse] = []
    unread_count: int = 0
    policy_provider_email: str | None = None
    is_onboarded: bool = False
    cc_emails: list[str] = []

    model_config = {"from_attributes": True}


class ClaimCaseEmailListItem(BaseModel):
    id: int
    direction: str
    from_email: str
    to_email: str
    subject: str | None = None
    email_date: datetime | None = None
    is_read: bool = False
    ai_suggested_status: str | None = None
    validation_status: str = "PENDING"
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
    uhid: str | None = None
    patient_name: str | None = None
    claim_number: str | None = None
    claim_status: str | None = None
    provider_name: str | None = None
    provider_id: str | None = None
    amount: float | None = None
    approved_amount: float | None = None
    status: str | None = None
    workflow_status: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProviderQueueItem(BaseModel):
    claim_case_id: UUID
    uhid: str | None = None
    patient_name: str | None = None
    claim_number: str | None = None
    hospital_id: UUID | None = None
    hospital_name: str | None = None
    amount: float | None = None
    status: str
    created_at: datetime


class PaginatedProviderQueueResponse(BaseModel):
    items: list[ProviderQueueItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class ClaimCaseFileItem(BaseModel):
    id: int
    email_id: int | None = None  # null for DRAFT files (uploaded but not yet sent)
    filename: str
    content_type: str | None = None
    file_size: int | None = None
    direction: str  # DRAFT (uploaded, not sent) | SENT (hospital → provider) | RECEIVED (provider → hospital)
    email_type: str | None = None  # SUBMITTED, ENHANCE_SUBMITTED, ADR_NMI, APPROVAL, ...
    view_url: str
    download_url: str
    created_at: datetime


class ClaimCaseSubmissionsResponse(BaseModel):
    files: list[ClaimCaseFileItem] = []


class ProviderActionRequest(BaseModel):
    status: str  # APPROVED, PARTIALLY_APPROVED, DENIED, ADR_NMI
    approved_amount: float | None = None
    claim_number: str | None = None
    remarks: str | None = None
    query_details: str | None = None
    documents_requested: str | None = None
    documents_list: list[str] | None = None
