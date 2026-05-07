from typing import Any

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
