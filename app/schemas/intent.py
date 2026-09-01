"""Schemas for the public /ai/intent endpoint.

The intent is deliberately MINIMAL and 100% accurate: it only says which table(s)
the question targets and what action it wants. All query details (measures,
dimensions, segments, filters, time) are chosen downstream by the Cube query
generator from the live /meta — so the intent never carries guessed values.
"""
from typing import Literal

from pydantic import BaseModel, Field


# The ONLY table names the intent may emit — exactly the 11 physical tables in the
# aiagent DB. Enforced by structured output so the LLM can never return a
# misspelled, hallucinated, or non-table name (routing between them is the
# prompt's job). NOTE: the derived UNION cube `status_tracking` is intentionally
# absent — it is not a DB table, so overall/unqualified turnaround asks for a
# clarification (pre-auth vs claim) instead.
TableName = Literal[
    "pre_auth",
    "claims",
    "hospitalization",
    "patient_personal_detail",
    "hospitals",
    "policy_provider_configs",
    "settlement_item",
    "settlement_batch",
    "preauth_status_tracking",
    "claim_status_tracking",
    "claim_case_emails",
]


class IntentRequest(BaseModel):
    query: str = Field(..., description="The user's natural-language question.")


class ScoredStr(BaseModel):
    value: str | None = Field(None, description="The chosen value (a table or action name), or null.")
    confidence: float = Field(0.0, description="How confident this value is correct — a number between 0.0 and 1.0.")


class ScoredTable(BaseModel):
    value: TableName | None = Field(None, description="The chosen table — MUST be one of the real table names, or null.")
    confidence: float = Field(0.0, description="How confident this table is correct — a number between 0.0 and 1.0.")


class ScoredTableList(BaseModel):
    value: list[TableName] = Field(default_factory=list, description="Chosen related tables — each MUST be a real table name.")
    confidence: float = Field(0.0, description="How confident this list is correct/complete — between 0.0 and 1.0.")


class ScoredStrList(BaseModel):
    value: list[str] = Field(default_factory=list, description="The chosen list of table names.")
    confidence: float = Field(0.0, description="How confident this list is correct/complete — between 0.0 and 1.0.")


class ScoredBool(BaseModel):
    value: bool = Field(True, description="Whether the question can be served by these tables.")
    confidence: float = Field(0.0, description="How confident about answerable — between 0.0 and 1.0.")


class TimeWindow(BaseModel):
    """A time window mentioned in the query. Present only when the query refers to
    a period; otherwise the whole `time` field is null."""
    relative: str | None = Field(
        None,
        description="Relative bucket when the query implies one: today | yesterday | this_week | last_week | "
                    "this_month | last_month | this_quarter | last_quarter | this_year | last_year | last_7_days | "
                    "last_30_days | last_90_days | custom. Use 'custom' for an explicit/named date range (then set "
                    "date_from/date_to). Keep 'this' vs 'last' exact.",
    )
    date_from: str | None = Field(None, description="Explicit start date YYYY-MM-DD (with relative='custom').")
    date_to: str | None = Field(None, description="Explicit end date YYYY-MM-DD (with relative='custom').")
    confidence: float = Field(0.0, description="How confident in this time window — between 0.0 and 1.0.")


class Intent(BaseModel):
    """Minimal intent: tables + action, each with a confidence score (0-1)."""
    query: str = Field("", description="The original user question, echoed verbatim (no confidence).")
    table: ScoredTable = Field(
        ...,
        description="Primary target table + confidence. value: a real table name (pre_auth, claims, "
                    "hospitalization, hospitals, patient_personal_detail, settlement_item, settlement_batch, "
                    "preauth_status_tracking, claim_status_tracking, policy_provider_configs, "
                    "claim_case_emails) or null.",
    )
    related_tables: ScoredTableList = Field(
        ...,
        description="Every OTHER table needed via joins, + confidence. Empty list if none.",
    )
    action: ScoredStr = Field(
        ...,
        description="Action + confidence. value: count | sum | avg | min | max | list | trend | ranking | lookup, or null.",
    )
    answerable: ScoredBool = Field(
        ...,
        description="Answerable flag + confidence. value=false when the question can't be served by these tables.",
    )
    clarification: str | None = Field(
        None,
        description="When the target table CANNOT be confidently determined, a short question to ask the user "
                    "(e.g. 'Did you mean pre-auths or claims?'). null when the table is clear. Never guess a table.",
    )
    metric: ScoredStr = Field(
        ...,
        description="FULL, SPECIFIC phrase for the exact quantity the user asks about, + confidence. "
                    "Name subject + any status/qualifier + aggregation; do NOT collapse to a bare word. "
                    "value examples: 'total pre-auth approved amount', 'count of pre-auths created and "
                    "cancelled', 'average claim turnaround time', 'count of pending pre-auths', "
                    "'total settled amount for SBI', 'max claimed amount'. value=null if unclear.",
    )
    time: TimeWindow | None = Field(
        None,
        description="The time window the query refers to, or null. Fill this ONLY if the question mentions a "
                    "time period; otherwise leave it null.",
    )


class CubeTimeDimension(BaseModel):
    dimension: str = Field(..., description="Qualified time dimension, e.g. pre_auth.created_at.")
    granularity: str | None = Field(None, description="day | week | month | quarter | year, or null for a plain filter.")
    dateRange: str | None = Field(None, description="RELATIVE range only: 'today','this week','this month','this year','last 7 days','last 30 days','last 90 days','last quarter'. Null for an explicit range (use dateFrom/dateTo instead).")
    dateFrom: str | None = Field(None, description="Explicit range START as full ISO date YYYY-MM-DD (e.g. 2026-06-20). Use with dateTo for a specific window.")
    dateTo: str | None = Field(None, description="Explicit range END as full ISO date YYYY-MM-DD (e.g. 2026-06-30).")


class CubeFilter(BaseModel):
    member: str = Field(..., description="Qualified member, e.g. claims.status.")
    operator: str = Field(..., description="equals|notEquals|contains|gt|gte|lt|lte|set|notSet|inDateRange|beforeDate|afterDate.")
    values: list[str] = Field(default_factory=list)


class CubeOrder(BaseModel):
    member: str = Field(..., description="Qualified measure/dimension to sort by.")
    direction: str = Field("desc", description="asc | desc.")


class GeneratedCubeQuery(BaseModel):
    """A Cube REST query, produced by the LLM from the scoped metadata. All member
    names must be fully qualified (cube.member) and exist in the provided metadata."""
    measures: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    segments: list[str] = Field(default_factory=list)
    timeDimensions: list[CubeTimeDimension] = Field(default_factory=list)
    filters: list[CubeFilter] = Field(default_factory=list)
    order: list[CubeOrder] = Field(default_factory=list)
    limit: int | None = None


class IntentQueryResponse(BaseModel):
    """Response of /ai/intent: the parsed intent, the Cube query generated from it
    (validated against Cube /meta), the metadata actually used, and any requested
    members that don't exist in the live Cube model."""
    intent: Intent
    cube_query: dict | None = Field(None, description="The generated Cube REST query (null if Cube is unreachable).")
    metadata_used: dict = Field(default_factory=dict, description="Slice of Cube /meta for the members used, grouped by cube.")
    unavailable_members: list[str] = Field(default_factory=list, description="Requested members not present in the live Cube model.")
    data: list[dict] | None = Field(None, description="Result rows from running the Cube query (null if not executed).")
    row_count: int | None = Field(None, description="Number of result rows.")
    generated_sql: dict | None = Field(None, description="The SQL Cube compiled from the cube_query: {sql, params}. null if unavailable.")
    notes: str | None = Field(None, description="Any warning (e.g. Cube unreachable, members dropped, execution failed).")
