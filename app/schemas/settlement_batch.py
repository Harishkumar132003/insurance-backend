from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ---- Header (settlement-level) ----------------------------------------------
class SettlementHeader(BaseModel):
    # Structured insurer link (AI-suggested on extract, editable). tpa_insurer
    # keeps the raw extracted name.
    policy_provider_id: UUID | None = None
    tpa_insurer: str | None = None
    total_settlement_amount: float | None = None
    payment_mode: str | None = None
    payment_batch: str | None = None
    utr_number: str | None = None
    settlement_number: str | None = None
    settlement_date: date | None = None
    hospital_account_number: str | None = None


# ---- Line item (per-claim) --------------------------------------------------
class SettlementItemIn(BaseModel):
    claim_number: str | None = None
    settled_amount: float | None = None
    claim_raised_amount: float | None = None
    disallowance: float | None = None
    disallowance_reason: str | None = None


class SettlementItemResponse(SettlementItemIn):
    id: int
    claim_case_id: UUID | None = None
    is_matched: bool = False


# ---- Stored-file reference --------------------------------------------------
class SettlementFileRef(BaseModel):
    """Pointer to the uploaded file, persisted to disk at extract time so the
    save step can reference it without re-uploading."""
    original_filename: str | None = None
    stored_filename: str | None = None
    file_path: str | None = None
    content_type: str | None = None


# ---- Extraction (preview, no DB write) --------------------------------------
class SettlementExtractItem(SettlementItemIn):
    """Extracted line + advisory match info (resolved against the DB but not
    yet persisted)."""
    is_matched: bool = False
    claim_case_id: UUID | None = None


class SettlementExtractResponse(BaseModel):
    header: SettlementHeader
    items: list[SettlementExtractItem] = Field(default_factory=list)
    matched_count: int = 0
    unmatched_count: int = 0
    # The uploaded file, already stored on disk — echoed back to send on save.
    source: SettlementFileRef | None = None


# ---- Live re-check of claim numbers (after the user edits) ------------------
class SettlementMatchRequest(BaseModel):
    claim_numbers: list[str] = Field(default_factory=list)


class SettlementMatchResult(BaseModel):
    claim_number: str
    is_matched: bool = False
    claim_case_id: UUID | None = None


# ---- Save payload (JSON) ----------------------------------------------------
class SettlementSavePayload(BaseModel):
    header: SettlementHeader
    items: list[SettlementItemIn] = Field(default_factory=list)
    source: SettlementFileRef | None = None


# ---- Responses --------------------------------------------------------------
class SettlementBatchResponse(BaseModel):
    id: UUID
    header: SettlementHeader
    source_original_filename: str | None = None
    items: list[SettlementItemResponse] = Field(default_factory=list)
    matched_count: int = 0
    unmatched_count: int = 0
    created_at: datetime


class SettlementBatchListItem(BaseModel):
    id: UUID
    tpa_insurer: str | None = None
    settlement_number: str | None = None
    settlement_date: date | None = None
    total_settlement_amount: float | None = None
    item_count: int = 0
    matched_count: int = 0
    source_original_filename: str | None = None
    created_at: datetime
