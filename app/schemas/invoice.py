from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


INVOICE_STATUSES = {"PAID", "PARTIALLY_PAID", "UNPAID"}
InvoiceStatus = Literal["PAID", "PARTIALLY_PAID", "UNPAID"]


class InvoicePaymentIn(BaseModel):
    payment_date: date
    amount: Decimal
    reference_id: str | None = None
    note: str | None = None


class InvoicePaymentUpdate(BaseModel):
    """Partial update — all fields optional. Only fields explicitly provided
    by the caller are applied (Pydantic v2 `model_fields_set`)."""
    payment_date: date | None = None
    amount: Decimal | None = None
    reference_id: str | None = None
    note: str | None = None


class InvoicePaymentOut(BaseModel):
    id: int
    payment_date: date
    amount: Decimal
    reference_id: str | None = None
    note: str | None = None
    sort_order: int = 0

    model_config = {"from_attributes": True}


class InvoiceCreate(BaseModel):
    """Payload for raising an invoice on a claim-approved case."""
    insurer_invoice_id: str = Field(..., min_length=1)
    insurer_amount: Decimal
    payments: list[InvoicePaymentIn] = Field(default_factory=list)


class InvoiceResponse(BaseModel):
    id: int
    claim_case_id: UUID
    insurer_invoice_id: str
    insurer_amount: Decimal
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
