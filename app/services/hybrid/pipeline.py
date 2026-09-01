"""End-to-end orchestration for the hybrid pipeline, plus the trace the endpoint returns.

    classify -> concepts -> [vector | keyword] -> RRF -> rerank -> select
             -> derive view -> SQL -> guard -> execute -> answer
"""
import asyncio
import json
import re
import time

from app.core.config import settings
from app.schemas.hybrid import (
    Classification,
    HealthResponse,
    HybridQueryResponse,
    HybridTrace,
)
from app.services.hybrid import bm25 as bm25_mod
from app.services.hybrid import execute as ex
from app.services.hybrid.common import chat_model, log, msg_text, new_rid, rid, short
from app.services.hybrid import identifiers as ident
from app.services.hybrid.concepts import entity_hint, extract_concepts
from app.services.hybrid.cube_meta import ALLOWED_VIEWS, derive_view, get_catalog
from app.services.hybrid.indexer import COLLECTION, collection_info
from app.services.hybrid.prompts import (
    ANSWER_PROMPT,
    CHAT_PROMPT,
    CLASSIFIER_PROMPT,
    NOT_PERMITTED_MESSAGE,
)
from app.services.hybrid.retrieval import retrieve, selected_qnames

# Rows handed to the summarizer. Ranking and limiting belong in SQL; this is only a
# guard against an enormous result blowing the context window.
ANSWER_ROW_BUDGET = 60

# "measure(preauth_tat_workflow.total_preauth_count)" -> "total_preauth_count"
_MEASURE_COL = re.compile(r"^measure\((?:[a-z0-9_]+\.)?([a-z0-9_]+)\)$", re.I)


class _Timer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.marks: dict[str, int] = {}
        self._last = self.t0

    def mark(self, name: str) -> None:
        now = time.perf_counter()
        self.marks[name] = int((now - self._last) * 1000)
        self._last = now

    def total(self) -> dict[str, int]:
        return {**self.marks, "total": int((time.perf_counter() - self.t0) * 1000)}


async def _probe_identifiers(concepts, hospital_id: str | None) -> list:
    """Resolve identifier-shaped literals against the data. Never raises."""
    try:
        catalog = await get_catalog()
        return await ident.resolve(concepts.entities, hospital_id, catalog)
    except Exception as e:  # noqa: BLE001 — a probe must never take the answer down
        log("identify", "probe stage FAILED (%s)", e)
        return []


def _inject_resolved_members(selection, resolutions: list, catalog: list) -> list[str]:
    """Force a resolved identifier's field into the member selection.

    Rewriting the SQL prompt alone is not enough. A wrong `kind` almost always ships
    with a matching wrong PHRASE, and the phrase is what drives retrieval — so the
    right column never makes it onto the shortlist, and `build_menu` would hand SQL
    generation a menu that cannot express the correct filter. Injecting the member
    here also lets `derive_view` pick a view that actually exposes it.
    """
    added: list[str] = []
    # Compared on the SHORT field name, not the qname: derive_view matches that way,
    # and build_menu re-points every member onto the derived view — so injecting
    # `master_hospital_360.uhid` when `preauth_tat_workflow.uhid` is already selected
    # would put the same field on the menu twice.
    present = {q.split(".", 1)[-1] for q in selected_qnames(selection)}

    for r in resolutions:
        field = r.resolved_field
        if not field or field in present:
            continue
        member = next((m for m in catalog if m.name == field and m.view == ident.PROBE_VIEW),
                      None) or next((m for m in catalog if m.name == field), None)
        if member is None:
            continue
        selection.dimensions.insert(0, member.qname)
        present.add(field)
        added.append(member.qname)

    if added:
        log("identify", "injected resolved member(s): %s", added)
    return added


async def classify(question: str) -> Classification:
    structured = chat_model(Classification)
    out: Classification = await structured.ainvoke([
        {"role": "system", "content": CLASSIFIER_PROMPT},
        {"role": "user", "content": question},
    ])
    log("classify", "%s (%.2f)", out.kind, out.confidence)
    return out


async def chat_reply(question: str) -> str:
    model = chat_model()
    resp = await model.ainvoke([
        {"role": "system", "content": CHAT_PROMPT},
        {"role": "user", "content": question},
    ])
    return msg_text(resp) or "Hi! Ask me about your pre-auths, claims, cases, providers or settlements."


def humanize(columns: list[str], rows: list[dict]) -> tuple[list[str], list[dict]]:
    """Turn Cube's raw column names into readable labels.

    Cube returns aggregates as `measure(view.total_preauth_count)`, which is unreadable
    in a table and confusing in a prose answer.
    """
    def clean(name: str) -> str:
        m = _MEASURE_COL.match(name)
        base = m.group(1) if m else name.split(".")[-1]
        return base.replace("_", " ").strip().title()

    keep = [c for c in columns if not (c.lower() == "id" or c.lower().endswith("_id"))] or columns
    labels, seen = [], {}
    for c in keep:
        lab = clean(c)
        seen[lab] = seen.get(lab, 0) + 1
        labels.append(lab if seen[lab] == 1 else f"{lab} {seen[lab]}")
    out_rows = [{lab: r.get(orig) for lab, orig in zip(labels, keep)} for r in rows]
    return labels, out_rows


async def summarize(question: str, columns: list[str], rows: list[dict]) -> str:
    labels, pretty = humanize(columns, rows)
    payload = json.dumps(pretty[:ANSWER_ROW_BUDGET], default=str)[:6000]
    model = chat_model()
    resp = await model.ainvoke([
        {"role": "system", "content": ANSWER_PROMPT},
        {"role": "user", "content": f"Question: {question}\nQUERY RESULT rows: {payload}"},
    ])
    return msg_text(resp) or "I couldn't find an answer to that."


async def run_pipeline(question: str, hospital_id: str | None = None,
                       stop_after: str = "answer",
                       include_trace: bool = True) -> HybridQueryResponse:
    new_rid()
    log("START", "%r | hospital=%s | stop_after=%s", short(question, 160), hospital_id, stop_after)
    timer = _Timer()
    trace = HybridTrace(request_id=rid())

    if not settings.OPENAI_API_KEY:
        return HybridQueryResponse(question=question, kind="db_query",
                                   answer="", notes="OPENAI_API_KEY is not configured.")

    # Classification and concept extraction don't depend on each other, so they run
    # together. A non-db_query wastes one cheap concepts call; every real question
    # saves a full round trip.
    cls, concepts = await asyncio.gather(classify(question), extract_concepts(question))
    timer.mark("classify_concepts")

    if cls.kind == "normal":
        answer = await chat_reply(question)
        trace.timings_ms = timer.total()
        return HybridQueryResponse(question=question, kind="normal", answer=answer,
                                   trace=trace if include_trace else None)
    if cls.kind == "not_permitted":
        trace.timings_ms = timer.total()
        return HybridQueryResponse(question=question, kind="not_permitted",
                                   answer=NOT_PERMITTED_MESSAGE,
                                   trace=trace if include_trace else None)

    # ---- retrieval ----
    trace.concepts = concepts

    # The probe is one cheap SELECT and shares no state with retrieval, so it rides
    # along for free instead of adding a serial round trip.
    r, resolutions = await asyncio.gather(
        retrieve(question, concepts),
        _probe_identifiers(concepts, hospital_id),
    )
    catalog = r["catalog"]
    trace.identifier_probe = [x.to_dict() for x in resolutions]
    trace.vector_hits = r["vector_hits"]
    trace.keyword_hits = r["keyword_hits"]
    trace.merged = r["merged"]
    trace.reranked = r["reranked"]
    trace.selected = r["selection"]
    trace.fanout_guard = r["fanout"]
    timer.mark("retrieval")

    _inject_resolved_members(r["selection"], resolutions, catalog)
    chosen = selected_qnames(r["selection"])
    view, derivation = derive_view(chosen, catalog)
    trace.view_derivation = derivation
    log("view", "%s (%s)", view, "fallback" if derivation.get("fallback") else "derived")
    timer.mark("view")

    if stop_after == "retrieval":
        trace.timings_ms = timer.total()
        return HybridQueryResponse(question=question, kind="db_query", view=view,
                                   answer="", notes="stopped after retrieval",
                                   trace=trace if include_trace else None)

    # ---- SQL ----
    menu = ex.build_menu(view, r["selection"], catalog)
    res = await ex.generate_guard_execute(
        question, menu, view, catalog,
        entity_hint=entity_hint(concepts, resolutions), hospital_id=hospital_id,
        execute=True,
    )
    trace.sql_attempts = res["attempts"]
    timer.mark("sql")

    if not res["ok"]:
        trace.timings_ms = timer.total()
        note = f"{res['stage']} failed: {short(res['error'], 400)}"
        log("done", "FAILED at %s", res["stage"])
        return HybridQueryResponse(
            question=question, kind="db_query", view=view, sql=res.get("sql"),
            answer=("I couldn't turn that into a valid query — please rephrase."
                    if res["stage"] == "guard" else "I couldn't run that query."),
            notes=note, trace=trace if include_trace else None)

    columns, rows = res["columns"], res["rows"]
    answer = await summarize(question, columns, rows)
    timer.mark("answer")
    labels, pretty = humanize(columns, rows)

    trace.timings_ms = timer.total()
    log("done", "%d rows | %dms total", len(rows), trace.timings_ms["total"])
    return HybridQueryResponse(
        question=question, kind="db_query", view=view, sql=res["sql"],
        columns=labels, rows=pretty, row_count=len(rows), answer=answer,
        trace=trace if include_trace else None)


async def health() -> HealthResponse:
    """Readiness without spending an LLM call."""
    out = HealthResponse(cube_ok=False, qdrant_ok=False, collection=COLLECTION)
    problems = []
    try:
        catalog = await get_catalog()
        out.cube_ok = True
        out.catalog_members = len(catalog)
        out.views = ALLOWED_VIEWS
        out.bm25_docs = bm25_mod.get_index(catalog).n
    except Exception as e:  # noqa: BLE001
        problems.append(f"cube: {e}")
    try:
        info = await collection_info()
        out.qdrant_ok = bool(info.get("exists"))
        out.collection_points = info.get("points", 0)
    except Exception as e:  # noqa: BLE001
        problems.append(f"qdrant: {e}")

    out.in_sync = bool(out.catalog_members and out.catalog_members == out.collection_points)
    if not out.in_sync and out.cube_ok and out.qdrant_ok:
        problems.append(f"index is stale: {out.collection_points} points vs "
                        f"{out.catalog_members} live members — run POST /ai2/reindex")
    out.detail = "; ".join(problems) or None
    return out
