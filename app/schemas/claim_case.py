from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field

from app.schemas.claim_case_document import ClaimCaseDocumentResponse


class ClaimCaseCreate(BaseModel):
    uhid: str
    hospital_id: UUID | None = None
    policy_provider_id: UUID


class CancelClaimCaseRequest(BaseModel):
    reason: str


class ClaimCaseResponse(BaseModel):
    id: UUID
    uhid: str
    hospital_id: UUID | None = None
    policy_provider_id: UUID
    claim_number: str | None = None
    thread_id: str | None = None
    current_stage: str
    # DB columns were renamed (status → case_status, claim_status →
    # preauth_outcome). Keep the original JSON keys for the API/frontend by
    # reading from the new attribute via validation_alias; output uses the
    # field name, so the response shape is unchanged.
    status: str = Field(validation_alias=AliasChoices("case_status", "status"))
    claim_status: str | None = Field(
        default=None, validation_alias=AliasChoices("preauth_outcome", "claim_status")
    )
    approved_amount: float | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class StatusHistoryItem(BaseModel):
    id: int
    stage: str
    status: str
    remarks: str | None = None
    approved_amount: float | None = None  # per-round amount (not cumulative)
    email_id: int | None = None  # FE click → GET /claim-cases/{id}/emails/{email_id}
    changed_by: str | None = None
    updated_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FormDataItem(BaseModel):
    id: int
    # Composed from the typed pre_auth_* tables by the controller (set as a
    # transient `.sections` attribute before serialization).
    sections: dict[str, Any] = {}
    preauth_status: str
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
    # See ClaimCaseResponse: JSON keys preserved, values read from the renamed
    # case_status / preauth_outcome columns via validation_alias.
    status: str = Field(validation_alias=AliasChoices("case_status", "status"))
    claim_status: str | None = Field(
        default=None, validation_alias=AliasChoices("preauth_outcome", "claim_status")
    )
    approved_amount: float | None = None
    # Headline status derived from approved_amount vs summary.requested_amount:
    #   approved < requested → "PARTIALLY_APPROVED"
    #   approved >= requested (or requested unknown) → "APPROVED"
    #   no money approved yet → falls back to claim_status / status
    main_status: str | None = None
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
    has_claim: bool = False
    # Snapshot of the Claim row when a claim has been raised on this case. Used
    # by the pre-auth detail page so it can display claim totals without making
    # a separate /claim request.
    claim_summary: dict | None = None
    # Invoice snapshot — null until the hospital raises an invoice on a
    # claim-approved case. Carries enough info for the detail page to render
    # the invoice card + payment list without a second round-trip.
    invoice: dict | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


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
    # ADR-only: hospital reviewer's edited list of insurer-requested documents.
    # Persisted as the email's ai_documents_list (replacing the AI suggestion)
    # AND, when claim_status is ADR_NMI, into an OPEN QueryLog so the
    # downstream ADR-response form can read it.
    documents_list: list[str] | None = None
    # Denial-only: hospital reviewer's edited insurer-stated reason. When
    # present, lands in StatusHistory.remarks instead of the default
    # "Manual edit of AI-extracted data" marker.
    remarks: str | None = None


class ClaimCaseSubmitForm(BaseModel):
    uhid: str
    policy_provider_id: UUID
    # Nested pre-auth sections: {patient_insured, treating_doctor, hospitalization}
    sections: dict[str, Any]


class ClaimCaseSubmitFormResponse(BaseModel):
    claim_case_id: UUID
    form_data_id: int
    status: str


class ClaimListItem(BaseModel):
    claim_case_id: UUID
    uhid: str | None = None
    patient_name: str | None = None
    age: int | str | None = None
    gender: str | None = None
    diagnosis: str | None = None
    icd_10: str | None = None
    claim_number: str | None = None
    claim_status: str | None = None
    provider_name: str | None = None
    provider_id: str | None = None
    amount: float | None = None
    approved_amount: float | None = None
    # Claim-stage figures (populated only when a Claim row exists).
    # claim_raised_amount = bill total submitted at raise time.
    # claim_approved_amount = insurer's claim-stage approval on the Claim row,
    # distinct from claim_cases.approved_amount (pre-auth cumulative).
    claim_raised_amount: float | None = None
    claim_approved_amount: float | None = None
    # Invoice (post-claim-approval) status: INVOICE_RAISED | PAID | UNPAID.
    # Null when no invoice has been raised yet for this case.
    invoice_status: str | None = None
    # Total settled amount for this case from uploaded settlement advices.
    settled_amount: float | None = None
    status: str | None = None
    workflow_status: str | None = None
    # True when this case's workflow status is one of the AWAITING_PROVIDER
    # states — drives a "needs your action" indicator on the provider list.
    awaiting_provider_action: bool = False
    unread_count: int = 0
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


