from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.claim_case_document import ClaimCaseDocumentResponse


class BillBreakdownItem(BaseModel):
    label: str
    amount: Decimal
    # Per-day lines carry the rate + day count; flat lines leave these None.
    rate: Decimal | None = None
    days: int | None = None


class ClaimCreate(BaseModel):
    bill_breakdown: list[BillBreakdownItem] = Field(default_factory=list)
    claimed_amount: Decimal
    remarks: str | None = None
    email_subject: str
    email_body: str


class ClaimDocumentGroup(BaseModel):
    document_type: str
    documents: list[ClaimCaseDocumentResponse]


class ClaimDraftSave(BaseModel):
    bill_breakdown: list[BillBreakdownItem] = Field(default_factory=list)
    claimed_amount: Decimal | None = None
    remarks: str | None = None


class ClaimDraftResponse(BaseModel):
    is_persisted: bool
    bill_breakdown: list[BillBreakdownItem] = Field(default_factory=list)
    claimed_amount: Decimal | None = None
    remarks: str | None = None
    updated_at: datetime | None = None


class ClaimResponse(BaseModel):
    id: int
    claim_case_id: UUID
    claimed_amount: Decimal
    approved_amount: Decimal | None = None
    status: str
    submitted_at: datetime | None = None
    processed_at: datetime | None = None
    created_at: datetime
    bill_breakdown: list[BillBreakdownItem] = Field(default_factory=list)
    remarks: str | None = None
    documents_by_type: list[ClaimDocumentGroup] = Field(default_factory=list)
    email_record_id: int | None = None
    is_onboarded: bool = False

    model_config = {"from_attributes": True}
