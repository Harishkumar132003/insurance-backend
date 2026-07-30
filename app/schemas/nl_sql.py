"""Schemas for the NL -> Cube SQL pipeline (classify -> concepts -> SQL)."""
from typing import Literal

from pydantic import BaseModel, Field

QueryKind = Literal["normal", "not_permitted", "db_query"]

# The VIEWS the agent queries. The LLM selects between the newly added views.
ViewName = Literal[
    "master_hospital_360",
    "desk_operations_queue",
    "preauth_tat_workflow",
    "claims_settlement_recon",
    "case_communications",
]


class Classification(BaseModel):
    kind: QueryKind = Field(..., description="normal | not_permitted | db_query.")
    confidence: float = Field(0.0, description="Confidence 0.0-1.0 in this classification.")


class ViewSelection(BaseModel):
    view: ViewName | None = Field(
        None,
        description="The SINGLE view that best answers the question "
                    "(master_hospital_360 | desk_operations_queue | preauth_tat_workflow | claims_settlement_recon | case_communications), or null if unclear.",
    )
    confidence: float = Field(0.0, description="Confidence 0.0-1.0 in the view choice.")


class ConceptList(BaseModel):
    metrics: list[str] = Field(
        default_factory=list,
        description="Cohesive business metrics — what is counted, summed, or calculated "
                    "(e.g. 'approved claims count', 'average TAT'). Searched as MEASURES.",
    )
    filters: list[str] = Field(
        default_factory=list,
        description="Generic filter/slice categories — how the data is sliced, restricted, "
                    "or grouped (e.g. 'date', 'hospital name', 'patient gender'). Never "
                    "literal values. Searched as DIMENSIONS.",
    )


class GeneratedSql(BaseModel):
    sql: str = Field(..., description="A single read-only PostgreSQL SELECT for the Cube SQL API.")


class NlSqlResponse(BaseModel):
    """Response of the public /ai/intent endpoint under the SQL pipeline."""
    query: str
    kind: QueryKind
    concepts: list[str] = Field(default_factory=list)
    sql: str | None = Field(None, description="The validated Cube SQL that was executed (null if not a db_query).")
    columns: list[str] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)
    row_count: int | None = None
    answer: str = Field("", description="The human-readable answer.")
    notes: str | None = None
