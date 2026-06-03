from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


INVOICE_STATUSES = {"INVOICE_RAISED", "PAID", "UNPAID"}
InvoiceStatus = Literal["INVOICE_RAISED", "PAID", "UNPAID"]


class InvoicePaymentIn(BaseModel):
    payment_date: date
    amount: Decimal
    note: str | None = None


class InvoicePaymentOut(InvoicePaymentIn):
    id: int
    sort_order: int = 0

    model_config = {"from_attributes": True}


class InvoiceCreate(BaseModel):
    """Payload for raising an invoice on a claim-approved case."""
    insurer_invoice_id: str = Field(..., min_length=1)
    insurer_amount: Decimal
    reference_id: str | None = None
    payments: list[InvoicePaymentIn] = Field(default_factory=list)


class InvoiceStatusUpdate(BaseModel):
    status: InvoiceStatus


class InvoiceReferenceUpdate(BaseModel):
    reference_id: str | None = None


class InvoiceResponse(BaseModel):
    id: int
    claim_case_id: UUID
    insurer_invoice_id: str
    insurer_amount: Decimal
    reference_id: str | None = None
    status: InvoiceStatus
    payments: list[InvoicePaymentOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class InvoiceListItem(BaseModel):
    """Row in the Raise Invoice tab list."""
    claim_case_id: UUID
    uhid: str | None = None
    patient_name: str | None = None
    provider_name: str | None = None
    claim_number: str | None = None
    claim_raised_amount: float | None = None
    claim_approved_amount: float | None = None
    # Invoice fields are null when no invoice has been raised yet.
    invoice_id: int | None = None
    invoice_status: InvoiceStatus | None = None
    insurer_invoice_id: str | None = None
    insurer_amount: float | None = None
    paid_total: float | None = None
    created_at: datetime
    invoice_created_at: datetime | None = None

    model_config = {"from_attributes": True}
