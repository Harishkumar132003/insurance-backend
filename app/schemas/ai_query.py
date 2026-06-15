from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AiQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000,
                          description="Natural-language question about this hospital's data.")


# ---- Query planner ---------------------------------------------------------
# The planner runs BEFORE the SQL executor. It decides what the user is really
# asking (which metric/column, time range, tables) or flags that the question is
# too ambiguous to answer. Its output is fed to the executor as an approved plan.
class PlanMetric(BaseModel):
    term: str = Field(..., description="The user's word for the figure, e.g. 'approved amount'.")
    column: str = Field(..., description="Exact table.column to use, e.g. 'hospitalization.approved_amount'.")
    aggregate: str = Field(..., description="SUM | COUNT | AVG | MIN | MAX | NONE.")


class PlanTimeRange(BaseModel):
    phrase: str = Field(..., description="The user's time phrase, e.g. 'this month'.")
    column: str = Field(..., description="Date column to filter on, e.g. 'created_at'.")
    expr: str = Field(..., description="SQL boolean expression for the range.")


class PlanEntity(BaseModel):
    type: str = Field(..., description="Entity kind, e.g. 'patient', 'provider', 'status'.")
    value: str = Field(..., description="The value to match, e.g. 'Harish'.")


class PlanStep(BaseModel):
    n: int = Field(..., description="1-based step number.")
    action: str = Field(..., description="Executor action, e.g. 'get_schema', 'run_query'.")
    purpose: str = Field(..., description="Why this step is needed.")
    depends_on: list[int] = Field(default_factory=list, description="Step numbers this depends on.")


class QueryPlan(BaseModel):
    needs_clarification: bool = Field(
        ..., description="True if the question is too ambiguous to answer without asking the user.")
    clarifying_question: Optional[str] = Field(
        None, description="One short question to ask the user (only when needs_clarification is true).")
    intent: Optional[str] = Field(None, description="Short machine label for the goal, e.g. 'sum_approved_amount'.")
    metric: Optional[PlanMetric] = Field(None, description="The figure being asked for, mapped to a column.")
    time_range: Optional[PlanTimeRange] = Field(None, description="Date filter, if any.")
    entities: list[PlanEntity] = Field(default_factory=list, description="Named filters (patient, provider, status).")
    tables: list[str] = Field(default_factory=list, description="Tables the query will read.")
    joins: list[str] = Field(default_factory=list, description="FK join conditions, if cross-table.")
    steps: list[PlanStep] = Field(default_factory=list, description="Ordered execution steps.")


class AiQueryResponse(BaseModel):
    answer: str = Field(..., description="Human-readable answer.")
    sql: list[str] = Field(default_factory=list,
                           description="SQL statement(s) the agent executed (for transparency).")
    columns: list[str] = Field(default_factory=list,
                               description="Columns of the last result set.")
    rows: list[dict[str, Any]] = Field(default_factory=list,
                                       description="Rows of the last result set (capped).")
    plan: Optional[QueryPlan] = Field(None, description="The planner's structured plan for this question.")


# ---- Persistent per-user chats ---------------------------------------------
class AiChatListItem(BaseModel):
    id: UUID
    title: str
    updated_at: datetime | None = None


class AiChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    sql: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None
    plan: Optional[QueryPlan] = Field(
        None, description="Planner output for this turn (transient; not persisted).")


class AiChatDetailResponse(BaseModel):
    id: UUID
    title: str
    messages: list[AiChatMessageResponse] = Field(default_factory=list)


class AiChatRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
