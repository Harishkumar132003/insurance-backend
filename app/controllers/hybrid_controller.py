"""Controller for the hybrid NL->Cube SQL test endpoints (thin orchestration)."""
import logging

from fastapi import HTTPException, status

from app.schemas.hybrid import (
    HealthResponse,
    HybridQueryRequest,
    HybridQueryResponse,
    ReindexResponse,
)
from app.services.hybrid import indexer, pipeline

logger = logging.getLogger("app.hybrid")


async def query(payload: HybridQueryRequest) -> HybridQueryResponse:
    try:
        return await pipeline.run_pipeline(
            question=payload.question,
            hospital_id=payload.hospital_id,
            stop_after=payload.stop_after,
            include_trace=payload.include_trace,
        )
    except Exception as e:  # noqa: BLE001 — surface a clean error, not a bare 500
        logger.exception("hybrid query failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Hybrid pipeline failed: {e}",
        )


async def reindex() -> ReindexResponse:
    try:
        summary = await indexer.reindex()
    except Exception as e:  # noqa: BLE001
        logger.exception("hybrid reindex failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Reindex failed: {e}",
        )
    return ReindexResponse(**summary)


async def health() -> HealthResponse:
    return await pipeline.health()
