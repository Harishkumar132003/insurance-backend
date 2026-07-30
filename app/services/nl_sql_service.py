"""NL -> Cube SQL pipeline.

    classify(query)
      ├─ normal        -> friendly LLM reply
      ├─ not_permitted -> fixed refusal
      └─ db_query      -> concepts -> vector retrieval (all cubes)
                          -> generate Cube SQL -> validate + RLS
                          -> run over Cube SQL API -> humanize

Reuses helpers from intent_service (Cube meta, embeddings, Qdrant, summarize).
The old intent/table-selection step is NOT used; INTENT_SYSTEM_PROMPT is kept in
intent_prompt.py for future use.
"""
import asyncio
import contextvars
import itertools
import json
import logging
import time

import sqlglot
from sqlglot import exp

from app.core.config import settings
from app.schemas.nl_sql import Classification, ConceptList, GeneratedSql, ViewSelection
from app.services import intent_service as _is
from app.services.nl_sql_prompt import (
    CHAT_PROMPT,
    CLASSIFIER_PROMPT,
    CONCEPTS_PROMPT,
    CUBE_SQL_PROMPT,
    NOT_PERMITTED_MESSAGE,
    VIEW_SELECT_PROMPT,
)

# The single view used when selection is unclear (widest coverage).
DEFAULT_VIEW = "master_hospital_360"

logger = logging.getLogger("app.nl_sql")

# Per-request step tracing. Every request gets a short id (via a contextvar so it
# propagates across awaits within the same task); every step logs under it, so a
# single request's trace reads top-to-bottom even under concurrency.
_rid: contextvars.ContextVar[str] = contextvars.ContextVar("nl_sql_rid", default="-")
_seq = itertools.count(1)


def _new_rid() -> str:
    rid = format(next(_seq) % 10000, "04d")
    _rid.set(rid)
    return rid


def _log(step: str, msg: str = "", *args) -> None:
    """Emit one step line: [nl_sql:0007] STEP | detail."""
    body = (msg % args) if args else msg
    logger.info("[nl_sql:%s] %-9s%s", _rid.get(), step, (" | " + body) if body else "")


def _short(text: str, n: int = 300) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n] + "…"


def _chat_model(structured=None, temperature: float = 0, issql: bool = False):
    from langchain.chat_models import init_chat_model
    model_name = settings.AI_SQL_MODEL if issql else settings.AI_QUERY_MODEL
    kwargs = {"api_key": settings.OPENAI_API_KEY}
    low = model_name.lower()
    if not any(tok in low for tok in ("o1-", "o1:", "o3-", "o3:", ":o1", ":o3")):
        kwargs["temperature"] = temperature
    m = init_chat_model(model_name, **kwargs)
    return m.with_structured_output(structured) if structured is not None else m


# ---- 1. classify ----------------------------------------------------------
async def classify_query(query: str) -> Classification:
    structured = _chat_model(Classification)
    out: Classification = await structured.ainvoke([
        {"role": "system", "content": CLASSIFIER_PROMPT},
        {"role": "user", "content": query},
    ])
    try:
        out.confidence = max(0.0, min(1.0, float(out.confidence)))
    except (TypeError, ValueError):
        out.confidence = 0.0
    _log("classify", "%s (%.2f)", out.kind, out.confidence)
    return out


async def generate_chat_reply(query: str) -> str:
    model = _chat_model()
    resp = await model.ainvoke([
        {"role": "system", "content": CHAT_PROMPT},
        {"role": "user", "content": query},
    ])
    reply = _is._msg_text(resp) or "Hi! Ask me about your pre-auths, claims, cases, providers or settlements."
    _log("chat-reply", "%s", _short(reply))
    return reply


# ---- 1b. view selection (picks the ONE view to query) ---------------------
async def select_view(query: str) -> str:
    structured = _chat_model(ViewSelection)
    out: ViewSelection = await structured.ainvoke([
        {"role": "system", "content": VIEW_SELECT_PROMPT},
        {"role": "user", "content": query},
    ])
    view = out.view or DEFAULT_VIEW
    _log("view", "%s (%.2f)", view, out.confidence or 0.0)
    return view


# ---- 2. concepts ----------------------------------------------------------
async def extract_concepts(query: str) -> tuple[list[str], list[str]]:
    """Extract (metrics, filters): metrics are searched as MEASURES, filters as
    DIMENSIONS, each scoped to the selected view."""
    structured = _chat_model(ConceptList)
    out: ConceptList = await structured.ainvoke([
        {"role": "system", "content": CONCEPTS_PROMPT.replace("{user_query}", query)},
        {"role": "user", "content": query},
    ])
    metrics = [c.strip().lower() for c in (out.metrics or []) if c and c.strip()]
    filters = [c.strip().lower() for c in (out.filters or []) if c and c.strip()]
    _log("concepts", "metrics=%s | filters=%s", metrics, filters)
    return metrics, filters


# ---- 3. retrieval across ALL cubes ----------------------------------------
async def _embed_many(texts: list[str]) -> list[list]:
    """Embed several concepts in ONE OpenAI call."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    resp = await client.embeddings.create(model=settings.EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


async def _qdrant_search_scoped(client, vector: list, cubes: set | None, k: int) -> set:
    """Top-k relevant members, optionally FILTERED to a set of cubes."""
    body: dict = {"vector": vector, "limit": k, "with_payload": True}
    if cubes:
        body["filter"] = {"must": [{"key": "cube", "match": {"any": list(cubes)}}]}
    r = await client.post(
        f"{settings.QDRANT_URL}/collections/{settings.QDRANT_COLLECTION}/points/search",
        json=body,
    )
    r.raise_for_status()
    out = set()
    for p in r.json().get("result", []):
        pl = p.get("payload") or {}
        name, cube = pl.get("name"), pl.get("cube")
        if name and cube:
            out.add(f"{cube}.{name}")
    return out


# ---- Direct Postgres execution against the flat views ---------------------
import functools


@functools.lru_cache(maxsize=1)
def _pg_engine():
    from sqlalchemy import create_engine
    # Flat views live in the aiagent DB; the agent queries them directly (no Cube).
    return create_engine(settings.AIAGENT_DATABASE_URL, pool_pre_ping=True)


_PG_COLS: dict[str, list[tuple[str, str]]] = {}


def pg_view_columns(view: str) -> list[tuple[str, str]]:
    """(name, type) columns of a flat view, introspected once and cached."""
    if view not in _PG_COLS:
        from sqlalchemy import inspect
        _PG_COLS[view] = [(c["name"], str(c["type"]).lower()) for c in inspect(_pg_engine()).get_columns(view)]
    return _PG_COLS[view]


def view_menu(view: str) -> str:
    """Menu for the SQL generator: the ONE view + its flat columns. Hides id/fk
    columns (RLS injects hospital_id itself; the LLM never groups on raw ids)."""
    cols = pg_view_columns(view)
    lines = [f"target_view_name: {view}", "injected_schema_list:"]
    shown = 0
    for name, typ in cols:
        if name == "case_id" or name.endswith("_id"):
            continue
        lines.append(f"  {name} ({typ})")
        shown += 1
    menu = "\n".join(lines)
    # Log EVERYTHING retrieved for the query (the view + every column sent to the
    # LLM). This is the current "retrieval" — a full menu, not a vector top-k.
    retrieved = [n for n, _ in cols if n != "case_id" and not n.endswith("_id")]
    _log("retrieval", "view=%s | %d columns retrieved: %s", view, shown, retrieved)
    _log("retrieval-menu", "\n%s", menu)
    return menu


def _run_pg_blocking(sql: str) -> tuple[list, list]:
    from sqlalchemy import text
    with _pg_engine().connect() as c:
        r = c.execute(text(sql))
        cols = list(r.keys())
        rows = [dict(zip(cols, row)) for row in r.fetchall()]
    return cols, rows


async def run_direct_sql(sql: str) -> tuple[list, list]:
    t0 = time.perf_counter()
    cols, rows = await asyncio.to_thread(_run_pg_blocking, sql)
    _log("execute", "%d rows, cols=%s (%dms)", len(rows), cols, int((time.perf_counter() - t0) * 1000))
    return cols, rows


# ---- Vector retrieval of view columns (filtered by domain_view) -----------
VIEWS = [
    "master_hospital_360",
    "desk_operations_queue",
    "preauth_tat_workflow",
    "claims_settlement_recon",
    "case_communications",
]
# Single Qdrant collection (from settings.QDRANT_COLLECTION = cube_metadata_openai).
# reindex_view_columns() rebuilds it to hold the real flat view columns.
VIEW_COL_COLLECTION = settings.QDRANT_COLLECTION

# Human descriptions for the flat view columns — embedded so concepts retrieve the
# right column, and shown to the SQL LLM (the status enum values fix "pending" etc.).
_COL_DESC = {
    "preauth_status": "Pre-auth workflow status. Values: DRAFT, SUBMITTED, ENHANCE_SUBMITTED, "
                      "ADR_SUBMITTED, RECONSIDER, ADR_NMI, APPROVED, PARTIALLY_APPROVED, "
                      "ENHANCEMENT_APPROVED, DENIED, ENHANCEMENT_DENIED, CANCELLED, UNKNOWN. "
                      "'pending'/'awaiting insurer' = SUBMITTED, ENHANCE_SUBMITTED, ADR_SUBMITTED, RECONSIDER.",
    "claim_status": "Claim workflow status (CLAIM_-prefixed). Values: CLAIM_SUBMITTED, "
                    "CLAIM_ADR_SUBMITTED, CLAIM_RECONSIDER, CLAIM_ADR_NMI, CLAIM_APPROVED, "
                    "CLAIM_PARTIALLY_APPROVED, CLAIM_DENIED, CLAIM_UNKNOWN.",
    "current_stage": "Which stage the case is in: PRE_AUTH or CLAIM.",
    "case_status": "Overall case status (mirrors the active stage's status).",
    "preauth_raised_amount": "Requested (raised) pre-auth amount, INR.",
    "preauth_approved_amount": "Approved pre-auth amount, INR (> 0 means approved).",
    "preauth_shortfall_amount": "Raised minus approved pre-auth amount (shortfall), INR.",
    "claimed_amount": "Amount claimed on the claim, INR.",
    "claim_approved_amount": "Approved claim amount, INR (> 0 means approved).",
    "settled_amount": "Amount actually settled/paid by the insurer, INR.",
    "disallowance": "Amount disallowed / short-paid by the insurer, INR.",
    "avg_turnaround": "Average insurer turnaround time for the case's status transitions.",
    "max_turnaround": "Longest turnaround among the case's transitions.",
    "min_turnaround": "Shortest turnaround among the case's transitions.",
    "transition_count": "Number of status transitions (history length).",
    "adr_count": "Number of ADR / additional-information requests.",
    "email_count": "Number of correspondence emails on the case.",
    "patient_name": "Patient full name.",
    "gender": "Patient gender (Male / Female / …).",
    "age_years": "Patient age in years.",
    "occupation": "Patient occupation.",
    "corporate_name": "Corporate / employer the policy belongs to.",
    "policy_number": "Insurance policy number.",
    "has_other_insurance": "Whether the patient has other insurance (boolean).",
    "provider_name": "Insurer / TPA (provider) name — group or filter 'by provider' on this.",
    "tpa_name": "TPA name of the provider.",
    "hospital_name": "Treating hospital name — group or filter 'by hospital' on this.",
    "uhid": "Unique hospital patient id (UHID).",
    "claim_number": "Claim number identifier.",
    "created_at": "When the case/record was created — use for time filters and trends.",
    "submitted_at": "When the claim was submitted.",
    "processed_at": "When the claim was processed.",
}


def _col_desc(name: str, view: str) -> str:
    return _COL_DESC.get(name) or f"{name.replace('_', ' ')} on the {view} view."


async def reindex_view_columns() -> int:
    """(Re)build the Qdrant index of the flat Postgres view columns — one point per
    (domain_view, column), embedded on its description. Names match the real view
    columns so retrieved members are always valid to query."""
    import httpx
    base = settings.QDRANT_URL
    async with httpx.AsyncClient(timeout=30) as client:
        await client.delete(f"{base}/collections/{VIEW_COL_COLLECTION}")
        await client.put(f"{base}/collections/{VIEW_COL_COLLECTION}",
                         json={"vectors": {"size": 1536, "distance": "Cosine"}})
        texts, payloads = [], []
        for view in VIEWS:
            for name, typ in pg_view_columns(view):
                if name == "case_id" or name.endswith("_id"):
                    continue
                desc = _col_desc(name, view)
                texts.append(f"{view} column {name} ({typ}): {desc}")
                payloads.append({"domain_view": view, "name": name, "type": typ, "description": desc})
        vectors = await _embed_many(texts)
        points = [{"id": i, "vector": vectors[i], "payload": payloads[i]} for i in range(len(texts))]
        await client.put(f"{base}/collections/{VIEW_COL_COLLECTION}/points", json={"points": points})
    logger.info("reindex_view_columns: indexed %d columns across %d views", len(points), len(VIEWS))
    return len(points)


async def _qdrant_view_search(client, vector: list, view: str, k: int, member_types) -> dict:
    """Top-k relevant members for ONE concept, filtered to the selected domain_view
    AND member kind(s) (measure | dimension | segment). member_types may be a single
    kind or a list — matched with Qdrant's `any`."""
    types = [member_types] if isinstance(member_types, str) else list(member_types)
    body = {"vector": vector, "limit": k, "with_payload": True,
            "filter": {"must": [{"key": "domain_view", "match": {"value": view}},
                                {"key": "type", "match": {"any": types}}]}}
    r = await client.post(f"{settings.QDRANT_URL}/collections/{VIEW_COL_COLLECTION}/points/search", json=body)
    r.raise_for_status()
    out = {}
    for p in r.json().get("result", []):
        pl = p.get("payload") or {}
        if pl.get("name"):
            out[pl["name"]] = (pl.get("type", ""), pl.get("description", ""), p.get("score", 0.0))
    return out


# Top-k members retrieved per concept element and kind (metrics -> 3 measures;
# each filter -> 3 dimensions AND 3 segments).
PER_CONCEPT_TOPK = 3


async def vector_retrieve(view: str, metrics: list[str], filters: list[str]) -> str:
    """After concepts: search each metric as a MEASURE (top-3), and each filter as a
    DIMENSION (top-3) AND a SEGMENT (top-3) — separate searches so both kinds are
    guaranteed slots. All scoped to the view's domain_view, unioned into the SQL menu.
    Fails loudly (raises) on any search error / empty result — never falls back to the
    full column menu."""
    import httpx
    if not metrics and not filters:
        _log("vsearch", "no concepts — raising (no full-menu fallback)")
        raise RuntimeError(f"no metrics/filters extracted for view={view}")
    k = PER_CONCEPT_TOPK
    # Embed each concept term once; reuse a filter term's vector for its dimension +
    # segment searches.
    terms = metrics + filters
    try:
        vectors = await _embed_many(terms)
        vec = dict(zip(terms, vectors))
        # metrics -> measures (1 search each); filters -> dimensions AND segments.
        async with httpx.AsyncClient(timeout=10) as client:
            searches = [_qdrant_view_search(client, vec[t], view, k, "measure") for t in metrics]
            for t in filters:
                searches.append(_qdrant_view_search(client, vec[t], view, k, "dimension"))
                searches.append(_qdrant_view_search(client, vec[t], view, k, "segment"))
            results = await asyncio.gather(*searches)
    except Exception as e:  # noqa: BLE001 — TEST: fail loudly, never fall back to the full menu
        _log("vsearch", "FAILED (%s) — raising (no full-menu fallback)", e)
        raise RuntimeError(f"vector retrieval failed for view={view}: {e}") from e

    merged: dict = {}
    for res in results:
        for name, (typ, desc, score) in res.items():
            if name not in merged or score > merged[name][2]:
                merged[name] = (typ, desc, score)
    if not merged:
        _log("vsearch", "no hits — raising (no full-menu fallback)")
        raise RuntimeError(f"vector retrieval returned no columns for view={view}, "
                           f"metrics={metrics}, filters={filters}")

    ranked = sorted(merged.items(), key=lambda x: -x[1][2])
    _log("vsearch", "view=%s | %d searches (%d metrics, %d filters) -> %d columns: %s",
         view, len(results), len(metrics), len(filters), len(ranked),
         [(n, round(v[2], 3)) for n, v in ranked])
    lines = [f"target_view_name: {view}", "injected_schema_list:"]
    for name, (typ, desc, _score) in ranked:
        lines.append(f"  {name} ({typ}) — {desc}")
    menu = "\n".join(lines)
    _log("vsearch-menu", "\n%s", menu)
    return menu


def _all_member_names(meta: dict) -> set:
    names = set()
    for c in meta.get("cubes", []):
        for kind in ("measures", "dimensions"):
            for m in c.get(kind, []):
                names.add(m["name"])
    return names


def _sql_menu(meta: dict, include_only: set | None) -> str:
    """Menu for the SQL generator: per-cube MEASURES and DIMENSIONS (NO segments —
    Cube SQL has no segments; filters are expressed on dimensions). Always keeps
    each involved cube's count measure and time dimensions so common asks work."""
    lines = []
    for c in meta.get("cubes", []):
        cube = c["name"]
        block = []
        for kind in ("measures", "dimensions"):
            for m in c.get(kind, []):
                name = m["name"]
                # Hide id/fk columns (e.g. hospital_id) — RLS injects hospital_id
                # itself and the LLM should never group/filter on raw ids.
                if kind == "dimensions" and (name.endswith("_id") or name.endswith(".id")):
                    continue
                if include_only is not None:
                    essential = (kind == "measures" and name.endswith(".count")) or \
                                (kind == "dimensions" and m.get("type") == "time")
                    if name not in include_only and not essential:
                        continue
                desc = " ".join((m.get("description") or "").split())
                typ = m.get("type") or ""
                tag = "MEASURE" if kind == "measures" else f"dim/{typ}"
                block.append(f"  [{tag}] {name}" + (f" — {desc}" if desc else ""))
        if block:
            # Only show cubes that actually contribute a member (keeps the menu tight).
            if include_only is None or any(
                (mm["name"] in include_only) for kind in ("measures", "dimensions") for mm in c.get(kind, [])
            ) or True:
                lines.append(f"\n## table: {cube}")
                lines.extend(block)
    return "\n".join(lines)


# ---- 4. generate Cube SQL -------------------------------------------------
async def generate_cube_sql(question: str, menu: str, view: str) -> str:
    from datetime import date
    structured = _chat_model(GeneratedSql,issql=True)
    system = f"USER QUESTION: {question} TODAY date is {date.today().isoformat()}.\n\n" + CUBE_SQL_PROMPT.replace("{target_view_name}", view) + "\n" + menu
    _log("prompt", "%s", system)

    out: GeneratedSql = await structured.ainvoke([
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ])
    sql = (out.sql or "").strip().rstrip(";").strip()
    _log("gen-sql", "%s", sql)
    return sql


async def repair_cube_sql(question: str, menu: str, bad_sql: str, error: str, view: str) -> str:
    """Rewrite a failing query, feeding back the exact error (Cube's error lists the
    valid fields, so this reliably fixes hallucinated members / bad shapes)."""
    from datetime import date
    structured = _chat_model(GeneratedSql)
    system = (f"TODAY date is {date.today().isoformat()}.\n\n" + CUBE_SQL_PROMPT.replace("{target_view_name}", view)
              + "\n\nMENU (only these tables/columns):\n" + menu)
    user = (f"{question}\n\nYour previous SQL FAILED — fix it.\n\nPrevious SQL:\n{bad_sql}\n\n"
            f"Error:\n{error}\n\nRewrite using ONLY valid members from the MENU. If a "
            "per-status count measure does not exist, use MEASURE(<cube>.count) with a WHERE "
            "on the status dimension, or GROUP BY the status dimension.")
    out: GeneratedSql = await structured.ainvoke([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
    sql = (out.sql or "").strip().rstrip(";").strip()
    _log("repair", "%s", sql)
    return sql


# TEST MODE: bypass the validator and run the LLM SQL on the CUBE SQL API instead
# of Postgres, logging Cube's converted query (its CubeScan plan via EXPLAIN).
TEST_RUN_IN_CUBE = True


async def _explain_cube(sql: str) -> None:
    """Log how Cube CONVERTS the SQL (its logical/physical CubeScan plan)."""
    try:
        _cols, rows = await run_cube_sql("EXPLAIN " + sql)
        for r in rows:
            for k, v in r.items():
                _log("cube-plan", "%s = %s", k, _short(str(v), 900))
    except Exception as e:  # noqa: BLE001
        _log("cube-plan", "EXPLAIN failed: %s", _short(str(e), 200))


async def _generate_validate_execute(question: str, menu: str, view: str,
                                     hospital_id=None) -> dict:
    """Generate -> validate(+RLS) -> execute on Postgres, with ONE repair retry
    that feeds the failure back to the LLM. Returns {ok, sql, columns, rows} or
    {ok:False, stage, sql, error}."""
    sql = await generate_cube_sql(question, menu, view)

    if TEST_RUN_IN_CUBE:
        # Skip the validator; run the raw LLM SQL on Cube and log Cube's conversion.
        _log("TEST", "validator SKIPPED — running on Cube SQL API")
        _log("cube-sql", "%s", sql)
        await _explain_cube(sql)
        try:
            cols, rows = await run_cube_sql(sql)
            return {"ok": True, "sql": sql, "columns": cols, "rows": rows}
        except Exception as e:  # noqa: BLE001
            _log("execute", "Cube FAILED (%s) | %s", _short(str(e), 200), sql)
            return {"ok": False, "stage": "execute", "sql": sql, "error": str(e)}

    for attempt in (1, 2):
        try:
            safe = validate_sql(sql, view, hospital_id=hospital_id)
            _log("validate", "OK | %s", safe)
        except Exception as e:  # noqa: BLE001 — hallucinated column / unsafe shape
            _log("validate", "REJECTED (%s) | %s", e, sql)
            if attempt == 2:
                return {"ok": False, "stage": "validate", "sql": None, "error": str(e)}
            sql = await repair_cube_sql(question, menu, sql, str(e))
            continue
        try:
            cols, rows = await run_direct_sql(safe)
            return {"ok": True, "sql": safe, "columns": cols, "rows": rows}
        except Exception as e:  # noqa: BLE001 — Postgres execution error
            _log("execute", "FAILED (%s) | %s", _short(str(e), 200), safe)
            if attempt == 2:
                return {"ok": False, "stage": "execute", "sql": safe, "error": str(e)}
            sql = await repair_cube_sql(question, menu, safe, str(e))
    return {"ok": False, "stage": "execute", "sql": sql, "error": "exhausted retries"}


# ---- 5. validate + RLS ----------------------------------------------------
_FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
              exp.Merge, exp.Command, exp.Set)


class SqlValidationError(Exception):
    pass


def validate_sql(sql: str, view: str, hospital_id=None) -> str:
    """Allowlist-validate an LLM-generated flat SELECT against ONE Postgres view,
    then inject the hospital-scoping filter. Raises SqlValidationError on anything
    unsafe (multiple statements, non-SELECT, other tables, hallucinated columns)."""
    statements = [s for s in sqlglot.parse(sql, read="postgres") if s]
    if len(statements) != 1:
        raise SqlValidationError("expected exactly one statement")
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise SqlValidationError("only a single SELECT is allowed")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN):
            raise SqlValidationError(f"forbidden statement: {type(node).__name__}")

    # ONLY the selected view may be queried (blocks other tables / pg_catalog / injection).
    tables = {t.name for t in tree.find_all(exp.Table)}
    bad = {t for t in tables if t != view}
    if bad:
        raise SqlValidationError(f"only the '{view}' view may be queried; blocked {sorted(bad)}")

    # Every referenced column must be a REAL column of the view (or a SELECT alias).
    valid_cols = {c[0] for c in pg_view_columns(view)}
    aliases = {a.alias for a in tree.find_all(exp.Alias) if a.alias}
    allowed = valid_cols | aliases | {"hospital_id"}
    unknown = sorted({c.name for c in tree.find_all(exp.Column) if c.name and c.name not in allowed})
    if unknown:
        raise SqlValidationError(f"unknown column(s): {unknown}")

    # RLS: scope to the caller's hospital (all views expose hospital_id).
    if hospital_id:
        if "hospital_id" in valid_cols:
            tree = tree.where(exp.condition(f"{view}.hospital_id = '{str(hospital_id)}'"))
            _log("rls", "scoped to hospital via %s.hospital_id", view)
        else:
            _log("rls", "WARNING %s has no hospital_id — NOT scoped", view)

    # Cap unbounded result sets (a single aggregate with no GROUP BY returns one row).
    if not tree.args.get("limit") and tree.args.get("group") is not None:
        tree = tree.limit(200)
    return tree.sql(dialect="postgres")


# ---- 6. execute over Cube SQL API -----------------------------------------
def _run_sql_blocking(sql: str) -> tuple[list, list]:
    import psycopg2
    conn = psycopg2.connect(
        host=settings.CUBE_SQL_HOST, port=settings.CUBE_SQL_PORT,
        dbname=settings.CUBE_SQL_DB, user=settings.CUBE_SQL_USER,
        password=settings.CUBE_SQL_PASSWORD, connect_timeout=10,
    )
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(cols, r)) for r in cur.fetchall()] if cols else []
        cur.close()
        return cols, rows
    finally:
        conn.close()


async def run_cube_sql(sql: str) -> tuple[list, list]:
    t0 = time.perf_counter()
    cols, rows = await asyncio.to_thread(_run_sql_blocking, sql)
    _log("execute", "%d rows, cols=%s (%dms)", len(rows), cols, int((time.perf_counter() - t0) * 1000))
    return cols, rows


# ---- humanize a SQL result (columns are SELECT aliases, not qualified) ----
def _humanize_sql(columns: list, rows: list) -> tuple[list, list]:
    def is_technical(name: str) -> bool:
        last = name.lower()
        return last == "id" or last.endswith("_id") or last.endswith(".id")

    keep = [c for c in columns if not is_technical(c)] or columns

    def label(name: str) -> str:
        return name.split(".")[-1].replace("_", " ").strip().title()

    labels, seen = [], {}
    for c in keep:
        lab = label(c)
        seen[lab] = seen.get(lab, 0) + 1
        labels.append(lab if seen[lab] == 1 else f"{lab} {seen[lab]}")
    out_rows = [{lab: row.get(orig) for lab, orig in zip(labels, keep)} for row in rows]
    return labels, out_rows


# ---- orchestration --------------------------------------------------------
async def _db_flow(question: str, hospital_id=None) -> dict:
    """concepts -> retrieval -> Cube SQL -> run -> answer. Returns the done payload
    {answer, sql, columns, rows}."""
    t0 = time.perf_counter()
    view = await select_view(question)
    metrics, filters = await extract_concepts(question)
    menu = await vector_retrieve(view, metrics, filters)

    res = await _generate_validate_execute(question, menu, view, hospital_id=hospital_id)
    if not res["ok"]:
        if res["stage"] == "validate":
            return {"answer": "I couldn't turn that into a safe query — please rephrase.",
                    "sql": [], "columns": [], "rows": []}
        return {"answer": "I couldn't run that query. Please try rephrasing.",
                "sql": [res["sql"]] if res.get("sql") else [], "columns": [], "rows": []}
    safe_sql, columns, rows = res["sql"], res["columns"], res["rows"]

    answer = await _is.summarize_answer(question, rows)
    _log("answer", "%s", _short(answer))
    show_table = len(rows) > 1 or len(columns) > 3
    table_cols, table_rows = ([], [])
    if show_table:
        table_cols, table_rows = _humanize_sql(columns, rows)
    _log("done", "table=%s | %dms total", show_table, int((time.perf_counter() - t0) * 1000))
    return {"answer": answer, "sql": [safe_sql], "columns": table_cols, "rows": table_rows}


async def astream_answer(hospital_id, question: str, history: list[dict] | None = None):
    """SSE-ready generator for the AI Assistant, on the NL->Cube SQL pipeline.
    Yields {"event","data"}; final `done` carries {answer, sql, columns, rows}
    (sql holds the executed Cube SQL for the 'Show query' toggle)."""
    if not settings.OPENAI_API_KEY:
        yield {"event": "error", "data": {"detail": "OPENAI_API_KEY is not configured."}}
        return

    _new_rid()
    _log("START", "chat | hospital=%s | %r", hospital_id, _short(question, 200))
    yield {"event": "status", "data": {"stage": "understanding"}}
    cls = await classify_query(question)

    if cls.kind == "normal":
        _log("route", "normal -> chat reply")
        reply = await generate_chat_reply(question)
        yield {"event": "done", "data": {"answer": reply, "sql": [], "columns": [], "rows": []}}
        return
    if cls.kind == "not_permitted":
        _log("route", "not_permitted -> static refusal")
        yield {"event": "done", "data": {"answer": NOT_PERMITTED_MESSAGE, "sql": [], "columns": [], "rows": []}}
        return
    _log("route", "db_query -> SQL flow")

    yield {"event": "status", "data": {"stage": "building"}}
    payload = await _db_flow(question, hospital_id=hospital_id)
    yield {"event": "status", "data": {"stage": "answering"}}
    # sql needs to be JSON-serializable list of strings for the UI toggle.
    yield {"event": "done", "data": {
        "answer": payload["answer"],
        "sql": payload.get("sql", []),
        "columns": payload.get("columns", []),
        "rows": payload.get("rows", []),
    }}


async def answer_question(hospital_id, question: str, history: list[dict] | None = None) -> dict:
    """Non-streaming variant — drains astream_answer and returns the done payload."""
    result = None
    async for ev in astream_answer(hospital_id, question, history):
        if ev["event"] == "error":
            raise RuntimeError(ev["data"].get("detail", "AI error"))
        if ev["event"] == "done":
            result = ev["data"]
    return result or {"answer": "I couldn't produce an answer.", "sql": [], "columns": [], "rows": []}


# ---- public /ai/intent endpoint flow --------------------------------------
async def answer_public(query: str) -> dict:
    """Unauthenticated public flow (no hospital scoping) -> NlSqlResponse dict."""
    _new_rid()
    _log("START", "public | %r", _short(query, 200))
    cls = await classify_query(query)
    base = {"query": query, "kind": cls.kind, "concepts": [], "sql": None,
            "columns": [], "rows": [], "row_count": None, "answer": "", "notes": None}

    if cls.kind == "normal":
        _log("route", "normal -> chat reply")
        base["answer"] = await generate_chat_reply(query)
        return base
    if cls.kind == "not_permitted":
        _log("route", "not_permitted -> static refusal")
        base["answer"] = NOT_PERMITTED_MESSAGE
        return base
    _log("route", "db_query -> SQL flow")

    view = await select_view(query)
    metrics, filters = await extract_concepts(query)
    base["concepts"] = metrics + filters
    menu = await vector_retrieve(view, metrics, filters)

    res = await _generate_validate_execute(query, menu, view)
    base["sql"] = res.get("sql")
    if not res["ok"]:
        base["notes"] = f"{res['stage']} failed: {res['error']}"
        base["answer"] = ("I couldn't turn that into a safe query — please rephrase."
                          if res["stage"] == "validate" else "I couldn't run that query.")
        return base
    columns, rows = res["columns"], res["rows"]
    base["columns"], base["rows"], base["row_count"] = columns, rows, len(rows)
    base["answer"] = await _is.summarize_answer(query, rows)
    _log("answer", "%s", _short(base["answer"]))
    _log("done", "%d rows", len(rows))
    return base
