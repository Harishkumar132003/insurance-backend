"""Build the dedicated Qdrant collection for the hybrid pipeline.

Deliberately a SEPARATE collection from `cube_metadata_openai`. That one is written by
two different scripts with incompatible payload schemas (oasys-cube's
embed_views_openai.py writes semantic members; nl_sql_service.reindex_view_columns()
writes Postgres flat-view columns), so whichever ran last wins. v2 owns its own
collection and cannot be clobbered.

Two differences from the existing index that matter for retrieval quality:

  * the payload carries `qname` — the directly queryable
    `master_hospital_360.total_claim_count` — so a hit needs no reconstruction;
  * the embedded text has NO boilerplate labels. The existing index embeds
    "Domain View: …\nCube: …\nType: …\nName: …\nTitle: …\nDescription: …" on every
    single document, so six identical label tokens appear in all 401 vectors.
"""
import logging
import uuid

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.hybrid.cube_meta import ALLOWED_VIEWS, Member, get_catalog

logger = logging.getLogger("app.hybrid")

COLLECTION = "cube_members_v2"
VECTOR_SIZE = 1536          # text-embedding-3-small
EMBED_BATCH = 100


def embed_text(m: Member) -> str:
    """What actually gets embedded. Meaning first, structural hints last."""
    parts = [m.title or m.name.replace("_", " ")]
    if m.description:
        parts.append(m.description)
    kind = "metric" if m.kind == "measure" else ("boolean filter" if m.kind == "segment" else "attribute")
    parts.append(f"({kind}, field {m.name.replace('_', ' ')}, view {m.view.replace('_', ' ')})")
    return " ".join(parts)


def payload_of(m: Member) -> dict:
    return {
        "qname": m.qname,
        "view": m.view,
        "name": m.name,
        "kind": m.kind,
        "dtype": m.dtype,
        "agg": m.agg,
        "title": m.title,
        "description": m.description,
        "cube": m.cube,
    }


async def _embed_all(texts: list[str]) -> list[list[float]]:
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        chunk = texts[i:i + EMBED_BATCH]
        resp = await client.embeddings.create(model=settings.EMBED_MODEL, input=chunk)
        out.extend(d.embedding for d in resp.data)
        logger.info("hybrid/index: embedded %d/%d", len(out), len(texts))
    return out


async def reindex(collection: str = COLLECTION, force_meta: bool = True) -> dict:
    """Rebuild the collection from Cube /meta. Returns a summary dict."""
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    catalog = await get_catalog(force=force_meta)
    if not catalog:
        raise RuntimeError("Cube /meta returned no members for the allowed views.")

    texts = [embed_text(m) for m in catalog]
    vectors = await _embed_all(texts)

    base = settings.QDRANT_URL.rstrip("/")
    points = [
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, m.qname)),
            "vector": vec,
            "payload": {**payload_of(m), "text": txt},
        }
        for m, txt, vec in zip(catalog, texts, vectors)
    ]

    async with httpx.AsyncClient(timeout=60) as client:
        await client.delete(f"{base}/collections/{collection}")
        r = await client.put(
            f"{base}/collections/{collection}",
            json={"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}},
        )
        r.raise_for_status()
        for i in range(0, len(points), 100):
            r = await client.put(
                f"{base}/collections/{collection}/points?wait=true",
                json={"points": points[i:i + 100]},
            )
            r.raise_for_status()

    per_view: dict[str, int] = {}
    for m in catalog:
        per_view[m.view] = per_view.get(m.view, 0) + 1
    undescribed = [m.qname for m in catalog if not m.description]

    summary = {
        "collection": collection,
        "indexed": len(points),
        "views": len(ALLOWED_VIEWS),
        "per_view": per_view,
        "undescribed": undescribed,
    }
    logger.info("hybrid/index: %s", summary)
    return summary


async def collection_info(collection: str = COLLECTION) -> dict:
    """Point count / status, or {"exists": False} when the collection is absent."""
    base = settings.QDRANT_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{base}/collections/{collection}")
        if r.status_code == 404:
            return {"exists": False, "points": 0}
        r.raise_for_status()
        res = r.json().get("result", {})
    return {
        "exists": True,
        "points": res.get("points_count", 0),
        "status": res.get("status"),
        "vector_size": (res.get("config", {}).get("params", {}).get("vectors", {}) or {}).get("size"),
    }
