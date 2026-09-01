"""Hybrid retrieval: dense + lexical -> RRF -> LLM re-rank -> member selection.

The diagram, in code:

    concepts -> [ Qdrant top-20 | BM25 top-20 ] -> RRF merge -> dedupe by field
             -> LLM re-rank -> top 15
             -> LLM member selection -> final Cube members

Two deliberate departures from the production pipeline:

  * NO up-front view selection and NO Qdrant `type` filter. Searching every view and
    every member kind at once means a "metric" concept can still surface the segment
    that actually answers the question, and the target view is derived afterwards from
    what was chosen rather than guessed beforehand.
  * Retrieval never raises. Each stage degrades to the previous stage's output, because
    a partial answer beats a 500.
"""
import asyncio

import httpx

from app.core.config import settings
from app.schemas.hybrid import Concepts, Hit, MemberSelection, RerankResult
from app.services.hybrid import bm25 as bm25_mod
from app.services.hybrid.common import chat_model, embed_many, log
from app.services.hybrid.cube_meta import Member, by_qname, get_catalog
from app.services.hybrid.indexer import COLLECTION
from app.services.hybrid.prompts import RERANK_PROMPT, SELECT_PROMPT

VECTOR_TOPK = 20
KEYWORD_TOPK = 20
RRF_K = 60
MERGE_KEEP = 30
RERANK_TOPK = 15
ROLE_PRIOR = 1.15

# A phrase's role predicts which KIND of member should answer it. Used as a gentle
# boost after fusion — never as a filter, which is where the production pipeline
# loses answers.
_ROLE_KINDS = {
    "metric": {"measure"},
    "filter": {"segment", "dimension"},
    "grouping": {"dimension"},
    "time": {"dimension"},
}


def _hit(m: Member, score: float, phrase: str | None = None) -> Hit:
    return Hit(qname=m.qname, kind=m.kind, view=m.view, title=m.title,
               description=m.description, score=score, phrase=phrase)


# ---- 1. dense arm ----------------------------------------------------------
async def vector_search(concepts: Concepts, catalog: list[Member],
                        k: int = VECTOR_TOPK) -> list[Hit]:
    """One Qdrant search per phrase, plus one for the whole normalized question.
    Unfiltered: all 5 views and all 3 member kinds compete."""
    index = by_qname(catalog)
    probes = [(p.phrase, p.phrase) for p in concepts.phrases]
    if concepts.normalized_question:
        probes.append((concepts.normalized_question, None))

    try:
        vectors = await embed_many([t for t, _ in probes])
    except Exception as e:  # noqa: BLE001
        log("vector", "embedding FAILED (%s) — dense arm empty", e)
        return []

    url = f"{settings.QDRANT_URL.rstrip('/')}/collections/{COLLECTION}/points/search"
    best: dict[str, tuple[float, str | None]] = {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            async def one(vec, phrase):
                r = await client.post(url, json={"vector": vec, "limit": k, "with_payload": True})
                r.raise_for_status()
                return phrase, r.json().get("result", [])

            for phrase, points in await asyncio.gather(
                *(one(v, ph) for v, (_, ph) in zip(vectors, probes))
            ):
                for p in points:
                    q = (p.get("payload") or {}).get("qname")
                    s = float(p.get("score", 0.0))
                    if q and (q not in best or s > best[q][0]):
                        best[q] = (s, phrase)
    except Exception as e:  # noqa: BLE001
        log("vector", "Qdrant FAILED (%s) — dense arm empty", e)
        return []

    hits = []
    for i, (q, (s, phrase)) in enumerate(sorted(best.items(), key=lambda kv: -kv[1][0])[:k]):
        m = index.get(q)
        if m:
            h = _hit(m, s, phrase)
            h.rank = i + 1
            hits.append(h)
    log("vector", "%d hits: %s", len(hits), [(h.qname, round(h.score, 3)) for h in hits[:8]])
    return hits


# ---- 2. lexical arm --------------------------------------------------------
def keyword_search(concepts: Concepts, catalog: list[Member],
                   k: int = KEYWORD_TOPK) -> list[Hit]:
    """BM25 per phrase, with the phrase's expansions appended — the acronyms and
    lexical variants that dense embeddings handle worst."""
    index = by_qname(catalog)
    idx = bm25_mod.get_index(catalog)

    best: dict[str, tuple[float, str | None]] = {}
    queries = [(f"{p.phrase} {' '.join(p.expansions)}".strip(), p.phrase)
               for p in concepts.phrases]
    if concepts.normalized_question:
        queries.append((concepts.normalized_question, None))

    for query, phrase in queries:
        for qname, score in idx.search(query, k):
            if qname not in best or score > best[qname][0]:
                best[qname] = (score, phrase)

    hits = []
    for i, (q, (s, phrase)) in enumerate(sorted(best.items(), key=lambda kv: -kv[1][0])[:k]):
        m = index.get(q)
        if m:
            h = _hit(m, s, phrase)
            h.rank = i + 1
            hits.append(h)
    log("keyword", "%d hits: %s", len(hits), [(h.qname, round(h.score, 2)) for h in hits[:8]])
    return hits


# ---- 3. merge --------------------------------------------------------------
def _dedupe_by_field(hits: list[Hit]) -> list[Hit]:
    """Collapse a field's per-view copies down to its best-scoring one.

    The catalog holds 237 members but only 111 distinct field names — `uhid`,
    `claim_number` and `case_current_status` each appear on all five views. Left alone,
    most of a 30-candidate shortlist is the same handful of fields repeated, and the
    re-ranker's top 15 can resolve to as few as 7 real choices.

    Safe because nothing downstream reads the view prefix: `derive_view` matches on the
    short name, `build_menu` re-points every member onto the derived view, and
    `fanout_branch` reads `.cube`, which is identical across a field's copies. The view
    is DERIVED from the selected fields afterwards, so committing to one here would be
    meaningless anyway.

    Expects `hits` sorted best-first — the first copy seen is the one kept.
    """
    seen: set[str] = set()
    out: list[Hit] = []
    for h in hits:
        field = h.qname.split(".", 1)[-1]
        if field in seen:
            continue
        seen.add(field)
        out.append(h)
    return out


def rrf_merge(vector_hits: list[Hit], keyword_hits: list[Hit], concepts: Concepts,
              keep: int = MERGE_KEEP) -> list[Hit]:
    """Reciprocal Rank Fusion.

    RRF is the right primitive here because cosine similarity and BM25 scores are not
    on a comparable scale — fusing by RANK sidesteps normalisation entirely. A member
    found by only one arm still scores (one term instead of two), which is exactly what
    keeps BM25 useful: it exists to rescue members dense search never saw.
    """
    role_of = {p.phrase: p.role for p in concepts.phrases}
    fused: dict[str, float] = {}
    meta: dict[str, Hit] = {}

    for lst in (vector_hits, keyword_hits):
        for rank, h in enumerate(lst, start=1):
            fused[h.qname] = fused.get(h.qname, 0.0) + 1.0 / (RRF_K + rank)
            meta.setdefault(h.qname, h)

    out: list[Hit] = []
    for qname, score in fused.items():
        src = meta[qname]
        role = role_of.get(src.phrase or "")
        boosted = bool(role and src.kind in _ROLE_KINDS.get(role, set()))
        if boosted:
            score *= ROLE_PRIOR
        out.append(Hit(qname=qname, kind=src.kind, view=src.view, title=src.title,
                       description=src.description, score=score, phrase=src.phrase,
                       role_boost=boosted))

    out.sort(key=lambda h: (-h.score, h.qname))
    fused_n = len(out)
    out = _dedupe_by_field(out)
    collapsed = fused_n - len(out)
    out = out[:keep]
    for i, h in enumerate(out, start=1):
        h.rank = i

    both = len(set(h.qname for h in vector_hits) & set(h.qname for h in keyword_hits))
    log("merge", "%d candidates (%d in both arms, %d dense-only, %d lexical-only), "
        "%d duplicate per-view copies collapsed",
        len(out), both, len(vector_hits) - both, len(keyword_hits) - both, collapsed)
    return out


# ---- 4. LLM re-ranker ------------------------------------------------------
def _render(hits: list[Hit]) -> str:
    lines = []
    for h in hits:
        desc = h.description[:220]
        lines.append(f"- {h.qname} ({h.kind}) — {h.title}: {desc}")
    return "\n".join(lines)


async def llm_rerank(question: str, candidates: list[Hit],
                     k: int = RERANK_TOPK) -> list[Hit]:
    """Score the fused shortlist against the question. Falls back to the fused order
    on any failure — a re-ranker hiccup must not cost the whole answer."""
    if not candidates:
        return []
    valid = {h.qname: h for h in candidates}
    structured = chat_model(RerankResult)
    system = RERANK_PROMPT.replace("{top_k}", str(k))
    user = f"QUESTION: {question}\n\nCANDIDATES:\n{_render(candidates)}"

    try:
        out: RerankResult = await structured.ainvoke([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
    except Exception as e:  # noqa: BLE001
        log("rerank", "FAILED (%s) — keeping fused order", e)
        return candidates[:k]

    ranked: list[Hit] = []
    seen: set[str] = set()
    for r in out.ranked:
        src = valid.get(r.qname)          # post-filter: no hallucinated members
        if not src or r.qname in seen:
            continue
        seen.add(r.qname)
        ranked.append(Hit(qname=src.qname, kind=src.kind, view=src.view, title=src.title,
                          description=src.description, score=float(r.score),
                          phrase=src.phrase, reason=r.reason, rank=len(ranked) + 1))
        if len(ranked) >= k:
            break

    dropped = [r.qname for r in out.ranked if r.qname not in valid]
    if dropped:
        log("rerank", "dropped %d hallucinated qname(s): %s", len(dropped), dropped)
    if not ranked:
        log("rerank", "nothing survived — keeping fused order")
        return candidates[:k]

    log("rerank", "%d kept: %s", len(ranked), [(h.qname, round(h.score, 2)) for h in ranked])
    return ranked


# ---- 5. final member selection --------------------------------------------
async def select_members(question: str, concepts: Concepts,
                         ranked: list[Hit]) -> MemberSelection:
    """Commit to the members SQL will actually use, partitioned by how it uses them."""
    if not ranked:
        return MemberSelection(reasoning="no candidates retrieved")

    valid = {h.qname for h in ranked}
    structured = chat_model(MemberSelection)
    phrases = ", ".join(f"{p.phrase} ({p.role})" for p in concepts.phrases)
    user = (f"QUESTION: {question}\n"
            f"CONCEPTS: {phrases}\n\n"
            f"SHORTLIST:\n{_render(ranked)}")

    try:
        out: MemberSelection = await structured.ainvoke([
            {"role": "system", "content": SELECT_PROMPT},
            {"role": "user", "content": user},
        ])
    except Exception as e:  # noqa: BLE001
        log("select", "FAILED (%s) — falling back to the re-ranked top members", e)
        out = MemberSelection(reasoning=f"selection failed: {e}")

    def keep(names: list[str]) -> list[str]:
        return [n for n in dict.fromkeys(names or []) if n in valid]

    out.measures = keep(out.measures)
    out.dimensions = keep(out.dimensions)
    out.segments = keep(out.segments)
    if out.time_dimension and out.time_dimension not in valid:
        out.time_dimension = None

    # Never hand SQL generation an empty menu — fall back to the shortlist by kind.
    if not (out.measures or out.dimensions or out.segments):
        log("select", "empty selection — using the re-ranked shortlist as-is")
        out.measures = [h.qname for h in ranked if h.kind == "measure"][:3]
        out.dimensions = [h.qname for h in ranked if h.kind == "dimension"][:3]
        out.segments = [h.qname for h in ranked if h.kind == "segment"][:2]

    log("select", "measures=%s dimensions=%s segments=%s time=%s",
        out.measures, out.dimensions, out.segments, out.time_dimension)
    return out


def selected_qnames(sel: MemberSelection) -> list[str]:
    names = list(sel.measures) + list(sel.dimensions) + list(sel.segments)
    if sel.time_dimension:
        names.append(sel.time_dimension)
    return list(dict.fromkeys(names))


# ---- 6. multi-branch report -------------------------------------------------
def apply_fanout_guard(sel: MemberSelection, catalog: list[Member],
                       ranked: list[Hit]) -> tuple[MemberSelection, dict | None]:
    """Report when a question spans two `one_to_many` branches. It no longer DROPS the
    losing branch's measures, because the premise for dropping them was wrong.

    This used to keep the better-ranked branch and delete the rest, on the theory that
    two branches multiply rows and inflate every SUM. Measured against the live Cube
    instance, that does not happen: the SQL API resolves a multi-fact query into
    per-fact subqueries joined on the shared dimensions, and combined values match
    separately-queried ones exactly — two branches and three, plain, grouped by a
    dimension, grouped by time, and segment-filtered (see tests/test_fanout.py).

    Dropping was itself a wrong-answer source. "Pre-auth vs claim turnaround" selected
    both TAT measures, the loser was cut on a rank tie-break, and the SQL writer — left
    with one measure and two slots to fill — emitted it twice under two aliases. The
    answer read "both are 20.39 hours" when the true figures are 22.31 and 20.39.
    Nothing downstream was told a measure had gone missing, so nothing could object.

    The real fan-out traps are unrelated to branch mixing and are enforced in
    `guard_sql`: bare `COUNT(*)`, an unwrapped measure, and segments in SELECT/GROUP BY.
    """
    from app.services.hybrid.cube_meta import fanout_branch

    index = by_qname(catalog)

    branches: dict[str, list[str]] = {}
    for q in sel.measures:
        m = index.get(q)
        b = fanout_branch(m) if m else None
        if b:
            branches.setdefault(b, []).append(q)

    if len(branches) < 2:
        return sel, None

    info = {"branches": sorted(branches), "measures_by_branch": branches,
            "dropped_measures": [],
            "why": "multi-fact query kept intact — Cube resolves branches as separate "
                   "subqueries joined on shared dimensions"}
    log("fanout", "%d branches kept intact: %s", len(branches), sorted(branches))
    return sel, info


async def retrieve(question: str, concepts: Concepts) -> dict:
    """Run every retrieval stage and return the pieces the trace needs."""
    catalog = await get_catalog()
    vec_task = asyncio.create_task(vector_search(concepts, catalog))
    kw = keyword_search(concepts, catalog)          # pure CPU, no await needed
    vec = await vec_task

    merged = rrf_merge(vec, kw, concepts)
    ranked = await llm_rerank(question, merged)
    selection = await select_members(question, concepts, ranked)
    selection, fanout = apply_fanout_guard(selection, catalog, ranked)

    return {"catalog": catalog, "vector_hits": vec, "keyword_hits": kw,
            "merged": merged, "reranked": ranked, "selection": selection,
            "fanout": fanout}
