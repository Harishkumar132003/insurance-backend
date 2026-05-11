from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PartDLetterFields(BaseModel):
    """Editable Part-D field values. All optional — partial updates allowed.
    Bill-breakdown and summary fields are free text (the PDF renders them
    verbatim); approved_amount is the canonical numeric figure."""
    approved_amount: float | None = None
    claim_number: str | None = None
    # bill breakdown
    room_rent_per_day: str | None = None
    icu_rent_per_day: str | None = None
    nursing_charges_per_day: str | None = None
    consultant_visit_charges_per_day: str | None = None
    surgeon_anesthetist_fee: str | None = None
    others: str | None = None
    # authorization summary
    total_bill_amount: str | None = None
    deductions_detail: str | None = None
    discount: str | None = None
    co_pay: str | None = None
    deductibles: str | None = None
    total_authorised_amount: str | None = None
    amount_to_be_paid_by_insured: str | None = None
    remarks: str | None = None


# The field names a PUT may carry — used to apply partial updates without
# touching columns the caller didn't send.
PART_D_FIELD_NAMES: tuple[str, ...] = tuple(PartDLetterFields.model_fields.keys())


class PartDLetterResponse(PartDLetterFields):
    id: int | None = None
    claim_case_id: UUID
    claim_case_email_id: int
    attachment_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # False when the GET synthesised a stub (no row persisted yet) — the FE
    # uses this to tell "Part-D step not started" from "Part-D started".
    is_persisted: bool = False

    model_config = {"from_attributes": True}
