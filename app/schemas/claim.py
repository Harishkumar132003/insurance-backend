from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.claim_case_document import ClaimCaseDocumentResponse


class BillBreakdownItem(BaseModel):
    label: str
    amount: Decimal


class ClaimCreate(BaseModel):
    bill_breakdown: list[BillBreakdownItem] = Field(default_factory=list)
    claimed_amount: Decimal
    remarks: str | None = None
    email_subject: str
    email_body: str


class ClaimDocumentGroup(BaseModel):
    document_type: str
    documents: list[ClaimCaseDocumentResponse]


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
