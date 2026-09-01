"""Hybrid retrieval NL -> Cube SQL pipeline (v2, experimental test harness).

Served under /api/v1/ai2/*. Completely separate from /api/v1/ai/* — nothing here
touches the production nl_sql_service pipeline.

Unauthenticated, following the /ai/intent precedent, so it can be curl'd and
benchmarked without a token. `hospital_id` is an optional body field; when supplied the
generated SQL is scoped to it.
"""
from fastapi import APIRouter

from app.controllers import hybrid_controller
from app.schemas.hybrid import (
    HealthResponse,
    HybridQueryRequest,
    HybridQueryResponse,
    ReindexResponse,
)

router = APIRouter(prefix="/ai2", tags=["AI Hybrid NL->SQL (experimental)"])


@router.post("/query", response_model=HybridQueryResponse)
async def hybrid_query(payload: HybridQueryRequest):
    """Concept extraction -> parallel vector + BM25 retrieval -> RRF merge ->
    LLM re-rank -> LLM member selection -> derived view -> Cube SQL -> answer.

    The `trace` in the response carries every intermediate stage, so retrieval quality
    can be inspected directly. Set `stop_after="retrieval"` to skip SQL generation and
    execution while tuning.
    """
    return await hybrid_controller.query(payload)


@router.post("/reindex", response_model=ReindexResponse)
async def hybrid_reindex():
    """Rebuild the dedicated `cube_members_v2` Qdrant collection from Cube /meta.
    Does not touch `cube_metadata_openai`, which the production pipeline reads."""
    return await hybrid_controller.reindex()


@router.get("/health", response_model=HealthResponse)
async def hybrid_health():
    """Cube and Qdrant reachability, catalog size, index point count, and whether the
    two are in sync. Makes no LLM calls."""
    return await hybrid_controller.health()
