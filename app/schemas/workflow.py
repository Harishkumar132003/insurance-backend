from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class WorkflowRunRequest(BaseModel):
    input: dict[str, Any]


class ContextSummaryRequest(BaseModel):
    patient: dict[str, Any]
    policy: dict[str, Any]


class StepDebug(BaseModel):
    step: str
    resolved_url: str | None = None
    resolved_headers: dict[str, Any] | None = None
    resolved_body: dict[str, Any] | None = None
    response: Any = None
    error: str | None = None


class WorkflowRunResponse(BaseModel):
    summary: str
    data: dict[str, Any]


class ChronicConditionsCoverage(BaseModel):
    diabetes: str
    heart_disease: str
    hypertension: str
    hyperlipidemia: str
    osteoarthritis: str
    asthma_copd: str
    cancer: str
    alcohol_drug_abuse: str
    hiv_std: str
    other: str | None = None


class CostEstimates(BaseModel):
    room_rent: str | None = None
    investigation_cost: str | None = None
    icu_charges: str | None = None
    ot_charges: str | None = None
    professional_fees: str | None = None
    medicines_cost: str | None = None
    other_expenses: str | None = None
    package_charges: str | None = None
    total_cost: str | None = None


class PolicyWorkflowRunResponse(BaseModel):
    summary: str
    policy_number: str | None = None
    data: dict[str, Any]
    steps_debug: list[StepDebug]
    chronic_conditions: ChronicConditionsCoverage | None = None
    cost_estimates: CostEstimates | None = None


class ContextSummaryResponse(BaseModel):
    summary: str


class CaseSheetTreatment(BaseModel):
    treatment_details: str | None = None
    drug_route: list[str] = []
    surgery_icd_code: str | None = None
    injury_cause: str | None = None


class CaseSheetInvestigation(BaseModel):
    investigation_category: str
    investigation_name: str
    investigation_description: str | None = None


class CaseSheetFieldMeta(BaseModel):
    """How a single value was obtained. `confidence` reflects how directly the
    sheet stated it (HIGH copied verbatim / MEDIUM reformatted or interpreted /
    LOW inferred), and `source` is the verified verbatim fragment it came from."""
    confidence: str | None = None
    source: str | None = None


class CaseSheetFileRef(BaseModel):
    """One uploaded page. `index` addresses it in GET /case-sheets/{id}/files/{index}."""
    index: int
    original_filename: str | None = None
    content_type: str | None = None


class CaseSheetForCaseResponse(BaseModel):
    """The case sheet a saved claim was built from, for reopening the form:
    the document reference plus the per-field confidence and provenance.
    `extracted` lets the client hide a score once the user has changed the value
    it described."""
    case_sheet_id: UUID
    original_filename: str | None = None
    created_at: datetime | None = None
    extracted: dict[str, Any] = {}
    field_meta: dict[str, CaseSheetFieldMeta] = {}
    files: list[CaseSheetFileRef] = []


class CaseSheetExtractResponse(BaseModel):
    """Same {summary, data} envelope as WorkflowRunResponse — the AI-fill page
    treats a case sheet as an alternative source for the very same card, so it
    must unwrap identically. The repeatable groups and the per-field metadata
    travel alongside rather than inside `data`, which stays a flat value map."""
    summary: str
    data: dict[str, Any]
    field_meta: dict[str, CaseSheetFieldMeta] = {}
    treatments: list[CaseSheetTreatment] = []
    investigations: list[CaseSheetInvestigation] = []
    # The stored extraction record; echo it back on save to link the sheet to the
    # claim case it produced. None when nothing could be extracted.
    case_sheet_id: UUID | None = None
    files: list[CaseSheetFileRef] = []
