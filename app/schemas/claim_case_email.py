from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ClaimCaseEmailAttachmentResponse(BaseModel):
    id: int
    original_filename: str
    content_type: str | None = None
    file_size: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClaimCaseEmailResponse(BaseModel):
    id: int
    claim_case_id: UUID
    direction: str
    email_type: str | None = None
    from_email: str
    to_email: str
    subject: str | None = None
    body: str | None = None
    email_date: datetime | None = None
    is_read: bool = False
    provider_read: bool = True
    ai_suggested_status: str | None = None
    ai_suggested_amount: float | None = None
    ai_suggested_claim_number: str | None = None
    ai_query_details: str | None = None
    ai_documents_requested: str | None = None
    ai_documents_list: list[str] | None = None
    validation_status: str = "PENDING"
    validated_at: datetime | None = None
    validated_by: UUID | None = None
    created_at: datetime
    attachments: list[ClaimCaseEmailAttachmentResponse] = []

    model_config = {"from_attributes": True}


class ClaimCaseEmailListResponse(BaseModel):
    id: int
    direction: str
    email_type: str | None = None
    from_email: str
    to_email: str
    subject: str | None = None
    email_date: datetime | None = None
    is_read: bool = False
    provider_read: bool = True
    ai_suggested_status: str | None = None
    validation_status: str = "PENDING"
    created_at: datetime
    attachment_count: int = 0

    model_config = {"from_attributes": True}


class AllClaimCaseEmailListItem(BaseModel):
    id: int
    claim_case_id: UUID
    claim_number: str | None = None
    is_onboard_claim: bool = False
    direction: str
    email_type: str | None = None
    from_email: str
    to_email: str
    subject: str | None = None
    email_date: datetime | None = None
    is_read: bool = False
    provider_read: bool = True
    ai_suggested_status: str | None = None
    ai_suggested_claim_number: str | None = None
    ai_suggested_amount: float | None = None
    validation_status: str = "PENDING"
    is_latest: bool = False
    created_at: datetime
    attachment_count: int = 0
    attachments: list[ClaimCaseEmailAttachmentResponse] = []


class ClaimCaseEmailValidateRequest(BaseModel):
    validation_status: str  # "APPROVED" or "REJECTED"
    remarks: str | None = None


class PaginatedEmailListResponse(BaseModel):
    items: list[AllClaimCaseEmailListItem]
    total: int
    page: int
    page_size: int
    total_pages: int
