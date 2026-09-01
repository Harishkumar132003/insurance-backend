"""Schemas for the hybrid retrieval pipeline (v2 test harness).

The `trace` object is the point of this endpoint: it exposes every stage of the
diagram — concepts, both retrieval arms, the fused list, the re-ranked shortlist, the
final member selection — so retrieval quality can be inspected and scored without
guessing from the answer alone.
"""
from typing import Any, Literal

from pydantic import BaseModel, Field

QueryKind = Literal["normal", "not_permitted", "db_query"]
PhraseRole = Literal["metric", "filter", "grouping", "time"]
# `settlement` and `utr` exist because CUBE_SQL_PROMPT rule 9 already teaches
# settlement-number and UTR lookups; without a kind for them they fell into `other`.
EntityKind = Literal["provider", "hospital", "corporate", "patient",
                     "policy", "claim", "uhid", "settlement", "utr", "other"]


# ---- concept extraction ----------------------------------------------------
class SearchPhrase(BaseModel):
    """One canonical schema concept, e.g. "preauth approved amount"."""
    phrase: str = Field(..., description="A 2-5 word lowercase noun phrase in SCHEMA "
                                         "vocabulary, not the user's words. No literal values.")
    role: PhraseRole = Field("metric", description="metric = counted/summed/calculated; "
                                                   "filter = restricts rows; grouping = "
                                                   "breakdown axis; time = date field.")
    expansions: list[str] = Field(default_factory=list,
                                  description="Lexical variants and expanded acronyms for "
                                              "keyword search only (e.g. ADR -> NMI, query).")


class Entity(BaseModel):
    """A literal value lifted out of the question — never searched, passed to SQL."""
    value: str
    kind: EntityKind = Field(
        "other",
        description="What the value identifies. provider/hospital/corporate/patient are "
                    "NAMES (matched with ILIKE); policy/claim/uhid/settlement/utr are "
                    "IDENTIFIERS (matched with =). For a bare number, give your best "
                    "guess and move on — it is verified against the database before "
                    "SQL is written, so a wrong guess here is corrected, not fatal.")


class Concepts(BaseModel):
    phrases: list[SearchPhrase] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    time_phrase: str | None = Field(None, description="Literal time reference, e.g. 'last month'.")
    normalized_question: str = Field("", description="The question restated with acronyms "
                                                     "expanded; used as one extra retrieval probe.")


# ---- retrieval stages ------------------------------------------------------
class Hit(BaseModel):
    qname: str
    kind: str = ""
    view: str = ""
    title: str = ""
    description: str = ""
    score: float = 0.0
    rank: int | None = None
    phrase: str | None = Field(None, description="Which concept phrase surfaced this member.")
    role_boost: bool = Field(False, description="Whether the role prior was applied.")
    reason: str | None = Field(None, description="Re-ranker's justification.")


class MemberSelection(BaseModel):
    measures: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    segments: list[str] = Field(default_factory=list)
    time_dimension: str | None = None
    reasoning: str = ""


# ---- LLM structured outputs ------------------------------------------------
class Classification(BaseModel):
    kind: QueryKind = Field(..., description="normal | not_permitted | db_query.")
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class RankedMember(BaseModel):
    qname: str = Field(..., description="Exact qname copied from the candidate list.")
    score: float = Field(0.0, ge=0.0, le=1.0)
    reason: str = ""


class RerankResult(BaseModel):
    ranked: list[RankedMember] = Field(default_factory=list)


class GeneratedSql(BaseModel):
    sql: str = Field(..., description="A single read-only SELECT for the Cube SQL API.")


# ---- trace -----------------------------------------------------------------
class HybridTrace(BaseModel):
    request_id: str = ""
    concepts: Concepts | None = None
    vector_hits: list[Hit] = Field(default_factory=list)
    keyword_hits: list[Hit] = Field(default_factory=list)
    merged: list[Hit] = Field(default_factory=list)
    reranked: list[Hit] = Field(default_factory=list)
    selected: MemberSelection | None = None
    view_derivation: dict[str, Any] = Field(default_factory=dict)
    fanout_guard: dict[str, Any] | None = None
    identifier_probe: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per literal: which identifier fields actually contain it. Without "
                    "this a resolved and an unresolved run look identical afterwards.")
    sql_attempts: list[dict[str, Any]] = Field(default_factory=list)
    timings_ms: dict[str, int] = Field(default_factory=dict)


# ---- API -------------------------------------------------------------------
class HybridQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    hospital_id: str | None = Field(None, description="When set, a hospital_id filter is "
                                                      "injected into the generated SQL.")
    stop_after: Literal["retrieval", "answer"] = Field(
        "answer", description="'retrieval' returns the trace without generating or running SQL.")
    include_trace: bool = True


class HybridQueryResponse(BaseModel):
    question: str
    kind: QueryKind
    answer: str = ""
    view: str | None = None
    sql: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int | None = None
    notes: str | None = None
    trace: HybridTrace | None = None


class ReindexResponse(BaseModel):
    collection: str
    indexed: int
    views: int
    per_view: dict[str, int] = Field(default_factory=dict)
    undescribed: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    cube_ok: bool
    qdrant_ok: bool
    catalog_members: int = 0
    collection: str = ""
    collection_points: int = 0
    bm25_docs: int = 0
    in_sync: bool = False
    views: list[str] = Field(default_factory=list)
    detail: str | None = None
