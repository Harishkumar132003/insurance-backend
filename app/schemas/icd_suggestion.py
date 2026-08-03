from pydantic import BaseModel, Field


class IcdSuggestionRequest(BaseModel):
    """Clinical context for an ICD-10-PCS suggestion. Every field is optional —
    the pre-auth form posts whatever the user has typed so far, and the route
    rejects the request only when all of them are empty."""

    # treating_doctor section-level context
    provisional_diagnosis: str | None = None
    illness_description: str | None = None
    critical_findings: str | None = None
    past_history: str | None = None
    duration_days: int | None = None
    # the treatment row the button was clicked in
    treatment_details: str | None = None
    drug_route: list[str] | None = None   # multi-select: DRUG_ROUTES codes
    injury_cause: str | None = None
    # patient context — PCS selection can hinge on age/sex
    age_years: int | None = None
    gender: str | None = None


class IcdSuggestion(BaseModel):
    code: str
    description: str
    rationale: str | None = None


class IcdSuggestionResponse(BaseModel):
    suggestions: list[IcdSuggestion] = Field(default_factory=list)
