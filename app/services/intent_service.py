"""Intent detection for the public /ai/intent endpoint.

Builds the intent LLM context from the aiagent DB schema (real tables/columns/FKs,
introspected read-only). The output SHAPE is enforced by the Intent
structured-output schema (schemas/intent.py). Then asks the LLM (OpenAI
gpt-4o-mini, reused via AI_QUERY_MODEL) to map a natural-language query to one
structured Intent, and (in detect_intent_with_query) generates + runs a Cube query.
"""
import json
import logging
import time

from app.core.config import settings
from app.schemas.intent import GeneratedCubeQuery, Intent
from app.services.intent_prompt import INTENT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Lazily-built, cached context (built once per process).
_CONTEXT: str | None = None


# ---- Context: real schema from the aiagent DB ------------------------------
def _db_schema_context() -> str:
    """Introspect the aiagent DB for tables, columns and FK relationships.
    Read-only; returns a compact text block. Degrades to '' on any failure."""
    try:
        from sqlalchemy import create_engine, inspect

        engine = create_engine(settings.AIAGENT_DATABASE_URL)
        try:
            insp = inspect(engine)
            lines = ["REAL SCHEMA (aiagent DB):"]
            for table in sorted(insp.get_table_names(schema="public")):
                cols = []
                for c in insp.get_columns(table, schema="public"):
                    cols.append(f"{c['name']} {str(c['type']).lower()}")
                fks = []
                for fk in insp.get_foreign_keys(table, schema="public"):
                    if fk.get("constrained_columns") and fk.get("referred_table"):
                        fks.append(
                            f"{fk['constrained_columns'][0]} -> "
                            f"{fk['referred_table']}.{(fk.get('referred_columns') or ['id'])[0]}"
                        )
                line = f"- {table}({', '.join(cols)})"
                if fks:
                    line += "  FKs: " + "; ".join(fks)
                lines.append(line)
            return "\n".join(lines)
        finally:
            engine.dispose()
    except Exception as e:  # noqa: BLE001 — context is best-effort
        logger.warning("intent: could not introspect aiagent DB: %s", e)
        return ""


def _build_context() -> str:
    """Intent context = the real aiagent DB schema (tables/columns/FKs). The output
    SHAPE is enforced separately by the Intent structured-output schema (see
    schemas/intent.py), so no cube semantic-model or sample-JSON context is needed
    here. cube/sampleintent.json is retained only as human documentation."""
    return _db_schema_context()


def _context() -> str:
    global _CONTEXT
    if _CONTEXT is None:
        _CONTEXT = _build_context()
    return _CONTEXT




def _resolve_amount_ambiguity(intent: Intent) -> None:
    """Deterministic: 'approved amount' with no stage word is ambiguous (pre-auth
    vs claim approved) -> force a clarification. 'claimed'/'requested/raised amount'
    are unambiguous -> pin the table if the LLM left it blank."""
    ql = (intent.query or "").lower()
    staged = any(w in ql for w in ("pre-auth", "preauth", "pre auth", "claim"))
    if ("approved amount" in ql or "amount approved" in ql) and not staged:
        intent.table.value = None
        intent.action.value = None
        intent.answerable.value = False
        intent.clarification = "Do you mean the pre-auth approved amount or the claim approved amount?"
    elif "claimed amount" in ql and not intent.table.value:
        intent.table.value, intent.answerable.value, intent.clarification = "claims", True, None
    elif ("requested amount" in ql or "raised amount" in ql) and "approved" not in ql and not intent.table.value:
        intent.table.value, intent.answerable.value, intent.clarification = "pre_auth", True, None


async def detect_intent(query: str) -> Intent:
    """Map a natural-language query to a structured Intent via the LLM."""
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    from langchain.chat_models import init_chat_model

    model = init_chat_model(
        settings.AI_QUERY_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=0,
    )
    from datetime import date

    structured = model.with_structured_output(Intent)
    system = f"TODAY is {date.today().isoformat()}.\n\n" + INTENT_SYSTEM_PROMPT 
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": query},
    ]
    intent: Intent = await structured.ainvoke(messages)
    if not intent.query:
        intent.query = query
    # Guarantee every confidence is within [0.0, 1.0].
    scored_fields = [intent.table, intent.related_tables, intent.action, intent.answerable, intent.metric]
    if intent.time is not None:
        scored_fields.append(intent.time)
    for scored in scored_fields:
        try:
            scored.confidence = max(0.0, min(1.0, float(scored.confidence)))
        except (TypeError, ValueError):
            scored.confidence = 0.0
    _resolve_amount_ambiguity(intent)
    logger.info("intent | %s", json.dumps(intent.model_dump(), default=str))
    return intent


# ---- Cube: fetch /meta and build a validated Cube query --------------------
def _cube_token() -> str | None:
    """Sign a minimal JWT for Cube when a secret is configured (optional in dev)."""
    if not settings.CUBE_API_SECRET:
        return None
    try:
        import jwt
        return jwt.encode({}, settings.CUBE_API_SECRET, algorithm="HS256")
    except Exception as e:  # noqa: BLE001
        logger.warning("intent: could not sign Cube token: %s", e)
        return None


async def fetch_cube_meta() -> dict:
    """Fetch Cube's /meta (the authoritative live model)."""
    import httpx

    headers = {}
    tok = _cube_token()
    if tok:
        headers["Authorization"] = tok
    url = f"{settings.CUBE_API_URL}/cubejs-api/v1/meta"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


# Cube /meta rarely changes (only on model edits) — cache it per process to avoid
# refetching the full model on every request.
_META_CACHE: dict = {"data": None, "ts": 0.0}
_META_TTL = 300  # seconds


async def get_cube_meta_cached() -> dict:
    now = time.time()
    if _META_CACHE["data"] is None or (now - _META_CACHE["ts"]) > _META_TTL:
        _META_CACHE["data"] = await fetch_cube_meta()
        _META_CACHE["ts"] = now
    return _META_CACHE["data"]


def _filter_meta(meta: dict, cube_names: set[str]) -> dict:
    """Client-side 'jq select' — keep only the cubes we need (the intent's table
    and its join targets). This is the scoped metadata we send to the LLM."""
    if not cube_names:
        return meta
    return {"cubes": [c for c in meta.get("cubes", []) if c["name"] in cube_names]}


def _meta_summary_for_llm(scoped_meta: dict, include_only: set | None = None) -> str:
    """Compact, member-by-member description of the scoped cubes for the LLM.
    If include_only is given, keep only those qualified names — plus the essentials
    (each cube's count measure and any time dimension) so common asks never break."""
    lines = []
    for c in scoped_meta.get("cubes", []):
        lines.append(f"\n## cube: {c['name']}")
        for kind in ("measures", "dimensions", "segments"):
            for m in c.get(kind, []):
                name = m["name"]
                if include_only is not None:
                    essential = (kind == "measures" and name.endswith(".count")) or \
                                (kind == "dimensions" and m.get("type") == "time")
                    if name not in include_only and not essential:
                        continue
                d = " ".join((m.get("description") or "").split())
                t = f" [{m.get('type')}]" if m.get("type") else ""
                lines.append(f"  {kind[:-1]}: {name}{t}" + (f" — {d}" if d else ""))
    return "\n".join(lines)


async def _embed_query(text: str) -> list:
    """Embed the user query with the same model the Qdrant collection was built on."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    resp = await client.embeddings.create(model=settings.EMBED_MODEL, input=text)
    return resp.data[0].embedding


async def _qdrant_search(client, vector: list, cube: str, k: int) -> set:
    """Top-k relevant members for ONE cube. Returns qualified names (cube.member)."""
    body = {
        "vector": vector,
        "filter": {"must": [{"key": "cube", "match": {"value": cube}}]},
        "limit": k,
        "with_payload": True,
    }
    r = await client.post(
        f"{settings.QDRANT_URL}/collections/{settings.QDRANT_COLLECTION}/points/search",
        json=body,
    )
    r.raise_for_status()
    out = set()
    for p in r.json().get("result", []):
        pl = p.get("payload") or {}
        name, cb = pl.get("name"), pl.get("cube")
        if name and cb:
            out.add(f"{cb}.{name}")
    return out


async def _retrieve_member_menu(query: str, scoped_meta: dict) -> str:
    """Qdrant top-k per cube (the intent's table AND every related table), so each
    cube contributes its most relevant members. Falls back to the full menu on any
    failure or empty result."""
    cubes = [c["name"] for c in scoped_meta.get("cubes", [])]
    if not cubes:
        return _meta_summary_for_llm(scoped_meta)
    # Below the size threshold the full menu is small AND more reliable (top-k can
    # drop a needed member). Only retrieve when the menu is genuinely large.
    total_members = sum(
        len(c.get(kind, [])) for c in scoped_meta.get("cubes", [])
        for kind in ("measures", "dimensions", "segments")
    )
    if total_members <= settings.CUBE_RETRIEVAL_MIN_MEMBERS:
        logger.info("cube retrieval | full menu (%d members, cubes=%s) — below threshold",
                    total_members, cubes)
        return _meta_summary_for_llm(scoped_meta)
    k = settings.CUBE_RETRIEVAL_TOPK
    try:
        import asyncio

        import httpx

        vector = await _embed_query(query)
        async with httpx.AsyncClient(timeout=10) as client:
            results = await asyncio.gather(*[_qdrant_search(client, vector, c, k) for c in cubes])
        selected = set().union(*results) if results else set()
        if not selected:
            return _meta_summary_for_llm(scoped_meta)
        menu = _meta_summary_for_llm(scoped_meta, include_only=selected)
        logger.info("cube retrieval | q=%r | %d retrieved members: %s",
                    query, len(selected), sorted(selected))
        logger.info("cube retrieval | menu sent to LLM:\n%s", menu)
        return menu
    except Exception as e:  # noqa: BLE001 — degrade to the full menu
        logger.warning("cube retrieval failed (%s) — using full menu", e)
        return _meta_summary_for_llm(scoped_meta)


async def fetch_cube_sql(query: dict) -> dict | None:
    """Fetch the SQL Cube compiles from a query (via /sql, no execution).
    Returns {sql, params} or None on failure."""
    import json as _json

    import httpx

    headers = {}
    tok = _cube_token()
    if tok:
        headers["Authorization"] = tok
    url = f"{settings.CUBE_API_URL}/cubejs-api/v1/sql"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers=headers, params={"query": _json.dumps(query)})
            if r.status_code == 200:
                s = (r.json().get("sql") or {}).get("sql")
                if isinstance(s, list) and s:
                    return {"sql": s[0], "params": s[1] if len(s) > 1 else []}
    except Exception as e:  # noqa: BLE001 — SQL preview is best-effort
        logger.warning("intent: could not fetch Cube SQL: %s", e)
    return None


async def run_cube_query(query: dict) -> dict:
    """Execute a Cube query via /load and return the parsed body ({data, annotation}).
    Handles Cube's async 'Continue wait' by polling briefly. Raises on error."""
    import asyncio

    import httpx

    headers = {"Content-Type": "application/json"}
    tok = _cube_token()
    if tok:
        headers["Authorization"] = tok
    url = f"{settings.CUBE_API_URL}/cubejs-api/v1/load"
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(15):  # Cube may answer "Continue wait" while it computes
            r = await client.post(url, headers=headers, json={"query": query})
            if r.status_code == 200:
                body = r.json()
                if isinstance(body, dict) and body.get("error") == "Continue wait":
                    await asyncio.sleep(1)
                    continue
                return body
            try:
                detail = r.json().get("error")
            except Exception:  # noqa: BLE001
                detail = r.text
            raise RuntimeError(detail or f"Cube /load returned HTTP {r.status_code}")
    raise RuntimeError("Cube /load did not finish in time (Continue wait).")


# Cube's supported relative dateRange phrases. gpt-4o-mini sometimes emits a
# malformed value like "this year}]}," — normalize it back to the clean phrase so
# Cube actually applies the filter (an invalid string is silently ignored).
_KNOWN_RANGES = (
    "today", "yesterday", "this week", "this month", "this quarter", "this year",
    "last week", "last month", "last quarter", "last year",
    "last 7 days", "last 30 days", "last 90 days", "last 365 days",
)


def _clean_date_range(dr):
    if not isinstance(dr, str):
        return dr  # explicit [from, to] list — leave as-is
    s = dr.strip().lower()
    for k in _KNOWN_RANGES:
        if s.startswith(k):
            return k
    return dr


def _index_meta(meta: dict):
    """Return (measures, dimensions, segments) sets of qualified names + a lookup
    of {qualified_name: meta_object} for building metadata_used."""
    measures, dimensions, segments, lookup = set(), set(), set(), {}
    for c in meta.get("cubes", []):
        for kind, bucket in (("measures", measures), ("dimensions", dimensions), ("segments", segments)):
            for m in c.get(kind, []):
                bucket.add(m["name"])
                lookup[m["name"]] = {"cube": c["name"], "kind": kind, **{
                    k: m.get(k) for k in ("name", "title", "shortTitle", "type", "description") if m.get(k) is not None
                }}
    return measures, dimensions, segments, lookup


_CUBE_QUERY_PROMPT = """\
You generate a Cube REST API query from a user's question. You are given the
metadata for ONLY the relevant cube(s). Rules:
- Use ONLY the fully-qualified member names listed in the metadata (e.g.
  pre_auth.count, pre_auth.pending, hospitals.name). Never invent names.
- Money asks -> measures (sum/avg). Status/slice asks -> segments. Time asks ->
  timeDimensions with a relative dateRange (e.g. "this month", "last 30 days").
- Set granularity ONLY when the user asks for a trend/breakdown over time
  (e.g. "monthly", "per day", "trend", "over time"); otherwise leave it null so
  the result is a single total, not per-bucket rows.
- For a RELATIVE window (this month, last 30 days, …) set `dateRange`. For an
  EXPLICIT/partial window (e.g. "June 20-30", "between X and Y") set `dateFrom`
  and `dateTo` as full YYYY-MM-DD dates — resolve any missing year to the current
  year using TODAY below; do NOT put a range in `dateRange`.
- "how many" -> the count measure.
- BREAKDOWN "by <field>" / "per <field>" -> add ONLY that field's DIMENSION with
  the count measure, and NO segments. Cube returns one row per value.
  * "by status" -> dimensions:[pre_auth.preauth_status] (or claims.status),
    measures:[<cube>.count], segments:[]  (NEVER list submitted/denied/... segments)
  * "by hospital" -> dimensions:[hospitals.name]
  Stacking multiple segments ANDs them together (wrong) — do not do it for a
  breakdown.
- When grouping/filtering "by" an entity, use the human-readable NAME dimension,
  never an id/uuid column: by hospital -> hospitals.name; by provider / insurer /
  TPA -> policy_provider_configs.name (NOT hospitalization.policy_provider_id).
- "highest/largest/maximum SINGLE X" (one claim, one case) -> use the max_ measure
  (e.g. claims.max_claimed_amount, hospitalization.max_approved_amount), NOT a SUM
  with order+limit (that returns the total, not the single largest).
- "top N <entities> by X" -> group by the entity's name dimension, order by the
  measure desc, limit N.
- "unique/distinct <entity>" -> the count_distinct measure (e.g.
  patient_personal_detail.unique_patient_count), not plain count.
- Do NOT add a status / to_status / transition segment unless the question
  explicitly names that status. "pre-auth stage only", "overall", or "only" just
  restrict the stage/cube — they are NOT a status filter. For a plain turnaround
  question use ONLY the avg_turnaround measure (+ provider/time filters); never
  add to_submitted / to_approved / etc.
- LIST / "show me" / "list the N <entities> with their X" -> you MUST include an
  identifying DIMENSION (claims.claim_number/claims.id, patient name, etc.) so
  each entity is its OWN ROW. Add the requested per-entity fields (amounts as
  their measures — grouped by the id they become per-entity values). NEVER answer
  a list with only aggregate measures and no dimension — that collapses everything
  into a single total row.
- COMPARE / trend across periods (e.g. "April vs May", "each month") -> use ONE
  timeDimension with granularity month over a dateRange spanning the periods
  (returns one row per month). NEVER put two timeDimensions on the same field.
- "pre-auths converted to claims" / "conversions" -> use the claims conversion
  measure (a claim existing = a conversion); never mix pre_auth approval segments
  with a claims measure.
- "how many claims/pre-auths got settled / received a settlement" ->
  settlement_item.settled_case_count (distinct settled cases). "total settled /
  amount paid" -> settlement_item.total_settled_amount or
  settlement_batch.total_settlement_amount. "disallowance/deduction" ->
  settlement_item.total_disallowance.
- "NOT (yet) moved/converted to claims" / "no claim raised yet" / "still in
  pre-auth" -> hospitalization.pre_auth_stage_count (cases still in the PRE_AUTH
  stage) = the inverse of conversion. Do NOT use pre_auth pending/awaiting
  segments for this — "not moved to claims" is about the case stage, not the
  pre-auth decision status.
- LOOKUPS: match patient_name with the `contains` operator (partial, forgiving);
  match uhid / claim_number / policy_number with `equals`. When the field to
  RETURN is on a different cube than the field you FILTER (e.g. filter
  patient_personal_detail.patient_name, return hospitalization.case_status), put
  both members in the query — Cube joins them. The SPECIFIC field asked for MUST
  be in the output (preauth status -> pre_auth.preauth_status; claim status ->
  claims.status; approved amount -> the amount measure) — it is the answer; don't
  return only generic id fields.
- UHID is a string patient identifier. It is NOT a column on pre_auth — to filter
  a pre-auth question by uhid, filter hospitalization.uhid (or
  patient_personal_detail.uhid) and return pre_auth.preauth_status via the join.
  NEVER put a uhid value into a *_id / hospitalization_id filter (those are uuids). Add a couple of identifying dimensions (name,
  uhid) alongside it. Do NOT force limit 1 — one patient / uhid can have MULTIPLE
  pre-auths or claims, so return ALL matching rows (omit limit, or cap ~25). Use
  limit 1 ONLY when the user explicitly asks for "the latest"/"most recent".
- Follow the plan hint if given, but only use members present in the metadata.
- Return an empty query if nothing sensible maps.

METADATA (only these members are allowed):
"""


def _needed_cubes(intent: Intent) -> set[str]:
    """Cubes to include in the scoped meta: the intent's table + its join targets."""
    cubes: set[str] = set()
    if intent.table.value:
        cubes.add(intent.table.value)
    cubes |= set(intent.related_tables.value or [])
    return cubes


def _intent_hint(intent: Intent) -> str:
    """Minimal hint for the query-gen: just the action (count/sum/list/…)."""
    parts = []
    if intent.action.value:
        parts.append(f"action≈{intent.action.value}")
    if intent.metric.value:
        parts.append(f"metric≈{intent.metric.value}")
    tw = intent.time
    if tw and (tw.relative or tw.date_from):
        if tw.relative == "custom" and tw.date_from:
            parts.append(f"time≈{tw.date_from}..{tw.date_to}")
        elif tw.relative:
            parts.append(f"time≈{tw.relative}")
    return "; ".join(parts)


async def generate_cube_query(nl_query: str, intent: Intent, scoped_meta: dict) -> GeneratedCubeQuery:
    """Ask the LLM to write a Cube query using ONLY the scoped metadata, grounded
    by the intent's plan."""
    from langchain.chat_models import init_chat_model

    from datetime import date

    model = init_chat_model(settings.AI_QUERY_MODEL, api_key=settings.OPENAI_API_KEY, temperature=0)
    structured = model.with_structured_output(GeneratedCubeQuery)
    hint = _intent_hint(intent)
    user = nl_query + (f"\n\nPlan hint (map to the allowed members): {hint}" if hint else "")
    menu = await _retrieve_member_menu(nl_query, scoped_meta)  # Qdrant top-k per cube (fallback: full)
    system = f"TODAY is {date.today().isoformat()}.\n\n" + _CUBE_QUERY_PROMPT + menu
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return await structured.ainvoke(messages)


_STATUS_WORDS = ("approv", "deni", "reject", "submit", "query", "adr", "reconsider",
                 "cancel", "pending", "enhanc", "await")


def _strip_spurious_tat_segments(cube_query: dict, question: str) -> None:
    """Turnaround questions shouldn't carry a to_<status> transition segment unless
    the user actually named that status ('pre-auth stage only' is NOT a status
    filter). Removes to_* segments in that case — deterministic guard since the LLM
    keeps adding them."""
    if not cube_query:
        return
    if not any("turnaround" in m for m in cube_query.get("measures", [])):
        return
    segs = cube_query.get("segments") or []
    if not segs:
        return
    if any(w in (question or "").lower() for w in _STATUS_WORDS):
        return  # user named a status — keep the segment
    kept = [s for s in segs if not s.split(".")[-1].startswith("to_")]
    if kept:
        cube_query["segments"] = kept
    else:
        cube_query.pop("segments", None)


def _validate_generated(gen: GeneratedCubeQuery, meta: dict) -> dict:
    """Validate every member of an LLM-generated query against the scoped meta.
    Drops unknown members. Returns {cube_query, metadata_used, unavailable_members}."""
    measures, dimensions, segments, lookup = _index_meta(meta)
    used, unavailable = [], []

    def keep(name: str, valid: set) -> bool:
        if name in valid:
            used.append(name)
            return True
        unavailable.append(name)
        return False

    q: dict = {}
    ms = [m for m in gen.measures if keep(m, measures)]
    if ms:
        q["measures"] = ms
    dims = [d for d in gen.dimensions if keep(d, dimensions)]
    if dims:
        q["dimensions"] = dims
    segs = [s for s in gen.segments if keep(s, segments)]
    if segs:
        q["segments"] = segs

    tds = []
    for td in gen.timeDimensions:
        if keep(td.dimension, dimensions):
            entry: dict = {"dimension": td.dimension}
            if td.granularity:
                entry["granularity"] = td.granularity
            if td.dateFrom and td.dateTo:
                entry["dateRange"] = [td.dateFrom, td.dateTo]  # explicit window
            elif td.dateRange:
                entry["dateRange"] = _clean_date_range(td.dateRange)  # relative bucket (normalized)
            tds.append(entry)
    if tds:
        q["timeDimensions"] = tds

    fs = []
    for f in gen.filters:
        if f.member in dimensions or f.member in measures:
            used.append(f.member)
            fs.append({"member": f.member, "operator": f.operator, "values": [str(v) for v in f.values]})
        else:
            unavailable.append(f.member)
    if fs:
        q["filters"] = fs

    order = []
    for o in gen.order:
        if o.member in measures or o.member in dimensions:
            order.append([o.member, "asc" if o.direction == "asc" else "desc"])
        else:
            unavailable.append(o.member)
    if order:
        q["order"] = order
    if gen.limit:
        q["limit"] = gen.limit

    metadata_used: dict = {}
    for name in dict.fromkeys(used):
        info = lookup.get(name)
        if info:
            metadata_used.setdefault(info["cube"], {}).setdefault(info["kind"], []).append(
                {k: v for k, v in info.items() if k not in ("cube", "kind")}
            )

    return {"cube_query": q, "metadata_used": metadata_used,
            "unavailable_members": list(dict.fromkeys(unavailable))}


async def detect_intent_with_query(query: str) -> dict:
    """Full flow: NL -> intent -> fetch Cube meta -> build validated Cube query.
    Returns a dict matching IntentQueryResponse."""
    intent = await detect_intent(query)
    try:
        meta = await get_cube_meta_cached()
    except Exception as e:  # noqa: BLE001 — Cube optional/unreachable
        logger.warning("intent: Cube meta unreachable: %s", e)
        return {
            "intent": intent,
            "cube_query": None,
            "metadata_used": {},
            "unavailable_members": [],
            "data": None,
            "row_count": None,
            "generated_sql": None,
            "notes": "Cube /meta is unreachable — returning the intent only.",
        }

    if not intent.answerable.value or not intent.table.value:
        return {
            "intent": intent,
            "cube_query": None,
            "metadata_used": {},
            "unavailable_members": [],
            "data": None,
            "row_count": None,
            "generated_sql": None,
            "notes": intent.clarification or "Query is out of scope for the cube model — no Cube query generated.",
        }

    # Scope the metadata to the cubes we actually need (intent's table + joins),
    # send THAT to the LLM to generate the Cube query, then validate members.
    needed = _needed_cubes(intent)
    scoped_meta = _filter_meta(meta, needed)
    notes = []
    try:
        gen = await generate_cube_query(query, intent, scoped_meta)
        built = _validate_generated(gen, scoped_meta)
    except Exception as e:  # noqa: BLE001 — Cube query generation failed
        logger.warning("intent: Cube query generation failed: %s", e)
        return {
            "intent": intent,
            "cube_query": None,
            "metadata_used": {},
            "unavailable_members": [],
            "data": None,
            "row_count": None,
            "generated_sql": None,
            "notes": "Could not generate a Cube query for this question.",
        }

    # A lookup by name/uhid can legitimately match MANY records (a patient can
    # have several pre-auths/claims). Never let limit=1 truncate them unless the
    # user explicitly asked for a single/latest one.
    q = built.get("cube_query") or {}
    if intent.action.value == "lookup" and isinstance(q.get("limit"), int) and q["limit"] <= 1:
        ql = (intent.query or "").lower()
        if not any(w in ql for w in ("latest", "most recent", "last ", "the recent")):
            q["limit"] = 25

    if built["unavailable_members"]:
        notes.append("Some generated members are not in the live Cube model: "
                     + ", ".join(built["unavailable_members"]))

    # Fetch the compiled SQL (preview) and run the query for the rows.
    data, row_count, generated_sql = None, None, None
    if built["cube_query"]:
        generated_sql = await fetch_cube_sql(built["cube_query"])
        try:
            body = await run_cube_query(built["cube_query"])
            data = body.get("data", [])
            row_count = len(data)
        except Exception as e:  # noqa: BLE001
            notes.append(f"Cube query could not be executed: {e}")
    else:
        notes.append("No runnable Cube query was produced from the intent.")

    return {
        "intent": intent,
        **built,
        "data": data,
        "row_count": row_count,
        "generated_sql": generated_sql,
        "notes": " | ".join(notes) if notes else None,
    }


# ---- Authenticated, hospital-scoped chat streamer (used by the AI Assistant) ---
def _hospital_filter(table: str | None, meta: dict, hospital_id) -> dict | None:
    """A Cube filter that scopes results to the user's hospital. Uses the primary
    cube's hospital_id when present; falls back to hospitals.id or the
    hospitalization join (for cubes without hospital_id)."""
    if not hospital_id:
        return None
    _, dimensions, _, _ = _index_meta(meta)
    hid = str(hospital_id)
    if table and f"{table}.hospital_id" in dimensions:
        return {"member": f"{table}.hospital_id", "operator": "equals", "values": [hid]}
    if table == "hospitals" and "hospitals.id" in dimensions:
        return {"member": "hospitals.id", "operator": "equals", "values": [hid]}
    if "hospitalization.hospital_id" in dimensions:
        return {"member": "hospitalization.hospital_id", "operator": "equals", "values": [hid]}
    return None


_GRAINS = {"second", "minute", "hour", "day", "week", "month", "quarter", "year"}


def _fmt_time(val, grain: str):
    """Format a Cube time-bucket value (e.g. '2026-05-01T00:00:00.000') nicely."""
    if not isinstance(val, str):
        return val
    from datetime import datetime
    try:
        d = datetime.fromisoformat(val.replace("Z", "")[:19])
    except Exception:  # noqa: BLE001
        return val
    if grain in ("year",):
        return str(d.year)
    if grain in ("month", "quarter"):
        return d.strftime("%b %Y")          # May 2026
    return d.strftime("%d %b %Y")            # 01 May 2026


def _humanize_table(columns: list, data: list, meta: dict):
    """Turn technical member keys into hospital-friendly headers using Cube's
    shortTitle, drop internal id/uuid columns and duplicate raw time columns,
    format time buckets, and re-key the rows to match."""
    _, _, _, lookup = _index_meta(meta)

    # Cube returns both a granularity bucket (claims.submitted_at.month) and the
    # raw dimension (claims.submitted_at). Identify buckets + their raw base.
    gran, bases = {}, set()
    for c in columns:
        head, _, tail = c.rpartition(".")
        if tail in _GRAINS and head:
            gran[c] = tail
            bases.add(head)

    def is_technical(name: str) -> bool:
        last = name.split(".")[-1]
        return last == "id" or last.endswith("_id")  # PKs / uuids (hospital_id, …)

    keep = [c for c in columns if not is_technical(c) and c not in bases] or columns

    def label(name: str) -> str:
        if name in gran:
            return gran[name].capitalize()   # "Month"
        info = lookup.get(name) or {}
        if info.get("shortTitle"):
            return info["shortTitle"]
        if info.get("title"):
            return info["title"]
        return name.split(".", 1)[-1].replace(".", " ").replace("_", " ").title()

    labels, seen = [], {}
    for c in keep:
        lab = label(c)
        seen[lab] = seen.get(lab, 0) + 1
        labels.append(lab if seen[lab] == 1 else f"{lab} {seen[lab]}")

    def cell(col, val):
        return _fmt_time(val, gran[col]) if col in gran else val

    rows = [{lab: cell(orig, row.get(orig)) for lab, orig in zip(labels, keep)} for row in data]
    return labels, rows


def _msg_text(resp) -> str:
    c = getattr(resp, "content", resp)
    if isinstance(c, list):
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c).strip()
    return (c or "").strip()


_ANSWER_PROMPT = """\
You are a hospital insurance data assistant. Answer the user's question in plain
business language using ONLY the numbers in the QUERY RESULT rows (JSON). Match
the shape of the result:
- Single value (one number): state it in one clear sentence
  (e.g. "There are 15 pending pre-auths.").
- One record with a few fields: give them in a single sentence.
- Multiple rows (a list or breakdown): open with a one-line summary, then a short
  numbered list of up to 5 rows with their key values.
- No rows: say plainly that no matching records were found — never invent data.

Rules:
- Format money Indian-style with ₹ and commas (e.g. ₹1,23,456).
- Be concise and factual; add no analysis, advice, or filler.
- NEVER mention SQL, cubes, tables, columns, ids, joins, or that data was queried
  — the user only sees your sentence.
- Do not restate raw column names; use natural words (e.g. "approved amount")."""


async def summarize_answer(question: str, data: list | None) -> str:
    """Turn result rows into a human-readable answer."""
    from langchain.chat_models import init_chat_model

    model = init_chat_model(settings.AI_QUERY_MODEL, api_key=settings.OPENAI_API_KEY, temperature=0)
    rows = json.dumps(data or [], default=str)[:4000]
    messages = [
        {"role": "system", "content": _ANSWER_PROMPT},
        {"role": "user", "content": f"Question: {question}\nResult rows: {rows}"},
    ]
    resp = await model.ainvoke(messages)
    return _msg_text(resp) or "I couldn't find an answer to that."


async def astream_answer(hospital_id, question: str, history: list[dict] | None = None):
    """SSE-ready generator powering the AI Assistant: NL question -> intent ->
    hospital-scoped Cube query -> rows -> human-readable answer. Yields
    {"event", "data"} dicts; the final `done` carries {answer, sql, columns, rows}
    (sql holds the Cube query JSON for the 'Show query' toggle)."""
    if not settings.OPENAI_API_KEY:
        yield {"event": "error", "data": {"detail": "OPENAI_API_KEY is not configured."}}
        return

    yield {"event": "status", "data": {"stage": "understanding"}}
    intent = await detect_intent(question)

    if not intent.answerable.value or not intent.table.value:
        msg = intent.clarification or (
            "I can answer questions about your pre-auths, claims, cases, patients, "
            "settlements, providers and turnaround times. Could you rephrase?")
        yield {"event": "done", "data": {"answer": msg, "sql": [], "columns": [], "rows": []}}
        return

    try:
        meta = await get_cube_meta_cached()
    except Exception as e:  # noqa: BLE001
        logger.warning("assistant: Cube meta unreachable: %s", e)
        yield {"event": "error", "data": {"detail": "The analytics service is unavailable right now."}}
        return

    scoped_meta = _filter_meta(meta, _needed_cubes(intent))
    yield {"event": "status", "data": {"stage": "building"}}
    try:
        gen = await generate_cube_query(question, intent, scoped_meta)
        built = _validate_generated(gen, scoped_meta)
    except Exception as e:  # noqa: BLE001
        logger.warning("assistant: query-gen failed: %s", e)
        yield {"event": "done", "data": {
            "answer": "I couldn't turn that into a query — please rephrase.",
            "sql": [], "columns": [], "rows": [],
        }}
        return

    cube_query = built["cube_query"] or {}
    _strip_spurious_tat_segments(cube_query, question)
    hf = _hospital_filter(intent.table.value, meta, hospital_id)  # scope to the user's hospital
    if cube_query and hf:
        cube_query.setdefault("filters", []).append(hf)

    yield {"event": "status", "data": {"stage": "running"}}
    data: list = []
    if cube_query:
        try:
            body = await run_cube_query(cube_query)
            data = body.get("data", []) or []
        except Exception as e:  # noqa: BLE001
            logger.warning("assistant: cube /load failed: %s", e)

    yield {"event": "status", "data": {"stage": "answering"}}
    answer = await summarize_answer(question, data)
    columns = list(data[0].keys()) if data else []

    # Only attach a table when it adds value: a real list/breakdown (>1 row) or a
    # detail record with several fields (>3 columns). A single scalar/small
    # aggregate is fully covered by the answer sentence — no redundant table.
    show_table = len(data) > 1 or len(columns) > 3
    table_cols, table_rows = ([], [])
    if show_table:
        table_cols, table_rows = _humanize_table(columns, data, meta)  # friendly headers

    yield {"event": "done", "data": {
        "answer": answer,
        # Store the Cube query (not SQL) in the `sql` field for the UI toggle.
        "sql": [json.dumps(cube_query, indent=2)] if cube_query else [],
        "columns": table_cols,
        "rows": table_rows,
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
