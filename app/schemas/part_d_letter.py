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

    # ── Numeric bill breakdown (matches the pre-auth cost estimates) ──
    bd_room_rent: float | None = None        # per day
    bd_icu_charges: float | None = None      # per day
    bd_expected_days: int | None = None
    bd_icu_days: int | None = None
    bd_investigation_cost: float | None = None
    bd_ot_charges: float | None = None
    bd_professional_fees: float | None = None
    bd_medicines_cost: float | None = None
    bd_package_charges: float | None = None
    bd_other_expenses: float | None = None
    # ── Numeric authorisation summary (computed in the modal) ──
    as_total_bill_amount: float | None = None
    as_discount: float | None = None
    as_co_pay: float | None = None
    as_deductibles: float | None = None
    as_deductions: float | None = None
    as_amount_to_be_paid_by_insured: float | None = None


# The field names a PUT may carry — used to apply partial updates without
# touching columns the caller didn't send.
PART_D_FIELD_NAMES: tuple[str, ...] = tuple(PartDLetterFields.model_fields.keys())


class PartDLetterResponse(PartDLetterFields):
    id: int | None = None
    claim_case_id: UUID
    # Nullable: draft Part-Ds (saved before any approval round) have no email.
    claim_case_email_id: int | None = None
    attachment_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # False when the GET synthesised a stub (no row persisted yet) — the FE
    # uses this to tell "Part-D step not started" from "Part-D started".
    is_persisted: bool = False

    model_config = {"from_attributes": True}
