"""Natural-language → SQL agent for the hospital-admin assistant.

Follows the LangChain SQL-agent pattern (a ReAct agent given database tools):
the model lists tables, inspects schemas, writes a query, optionally checks it,
runs it, and reasons over the rows to answer in plain language — looping until
it can answer or gives up.

Safety is layered and does NOT rely on the prompt:
  • the tools execute through the read-only, RLS-scoped `oasys_ai_ro` role
    (app/db/readonly_session.py) — every row is already filtered to the
    caller's hospital, and writes are impossible;
  • `run_query` additionally passes SQL through sql_guard (SELECT-only, row cap)
    before execution.

The agent is built per request so its tools are bound to that caller's
hospital_id; nothing tenant-specific is shared between requests.
"""

import json
import logging
import re
from decimal import Decimal
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import text

from app.core.config import settings
from app.db.readonly_session import readonly_connection
from app.schemas.ai_query import QueryPlan
from app.services import sql_guard

logger = logging.getLogger(__name__)

# The agent may inspect/query only these tables (the read-only role is granted
# nothing else). `patients` is deliberately absent — it has no tenant column.
ALLOWED_TABLES = [
    "hospitals", "users", "hospitalization", "cc_emails", "execution_logs",
    "hospital_configs", "hospital_prompts", "hospital_provider_mappings",
    "pre_auth", "pre_auth_patient", "pre_auth_stay", "pre_auth_treatment",
    "claims", "settlements", "settlement_batch", "settlement_item", "status_history",
    "query_logs", "claim_case_emails", "claim_case_email_attachments",
    "claim_case_documents", "part_d_letters", "claim_bill_item",
    "policy_provider_configs", "form_templates", "email_templates",
    "summary_prompt_templates", "features",
]
_ALLOWED_SET = set(ALLOWED_TABLES)

# Domain map so the model knows what the (sometimes oddly named) tables mean.
# Physical names differ from intuition — `hospitalization` is the claim-case
# hub, `pre_auth` is the pre-auth form snapshot.
SCHEMA_GUIDE = """\
OASYS automates the cashless health-insurance workflow between a hospital and a
policy provider / TPA. Key tables (use get_schema for exact columns):

- hospitalization — THE CLAIM-CASE HUB (one row per case). Columns include
  hospital_id, policy_provider_id, current_stage ('PRE_AUTH'|'CLAIM'),
  case_status (workflow state), preauth_outcome (latest pre-auth outcome), created_at.
  Status outcome values: APPROVED, PARTIALLY_APPROVED, DENIED,
  ENHANCEMENT_APPROVED/DENIED, ADR_NMI, CANCELLED. "Awaiting insurer" =
  status in (SUBMITTED, ENHANCE_SUBMITTED, RECONSIDER, ADR_SUBMITTED,
  CLAIM_SUBMITTED, CLAIM_ADR_SUBMITTED, CLAIM_RECONSIDER).
- pre_auth — pre-auth form snapshot (form_data), FK claim_case_id -> hospitalization.id.
- pre_auth_patient / pre_auth_stay / pre_auth_treatment — patient, hospitalisation
  stay, and treatment details; FK form_data_id -> pre_auth.id.
- claims — final bill per case, FK claim_case_id -> hospitalization.id.
- SETTLEMENTS live in settlement_batch + settlement_item (the old `settlements`
  table is DEPRECATED and empty — never use it):
  - settlement_batch — settlement header: total_settlement_amount, settlement_date,
    tpa_insurer, utr_number, payment_mode; FK hospital_id.
  - settlement_item — per-claim settled line: settled_amount, claim_raised_amount,
    disallowance, claim_number, is_matched; FK batch_id -> settlement_batch.id,
    claim_case_id -> hospitalization.id.
- "Invoice" / "payment" questions: the invoice tables are DEPRECATED and not
  queryable. Treat any invoice / payment question as a SETTLEMENT question and
  answer it from settlement_batch / settlement_item (see SETTLEMENTS above).
- status_history — audit timeline of status changes, FK claim_case_id.
- query_logs — ADR / "need more info" requests, FK claim_case_id.
- claim_case_emails / _attachments / claim_case_documents / part_d_letters — case correspondence & docs.
- policy_provider_configs — insurers/TPAs (provider names), joined via
  hospitalization.policy_provider_id.
- claim_bill_item — per-line bill breakdown (label, amount) on a claim-stage
  pre_auth row; FK form_data_id -> pre_auth.id.
- hospital_provider_mappings — which insurers/TPAs this hospital is empanelled
  with, incl. MoU room-charge terms (is_active); FK hospital_id, policy_provider_id.
- hospitals — the hospital record itself (name, address, rohini_id, email). One row.
- users — staff login accounts for the hospital (email, role, access).
- cc_emails — CC email addresses copied on insurer correspondence, per provider.

SYSTEM / CONFIG tables — settings, templates and internals, NOT claims data.
Do NOT use these for data questions unless the user explicitly asks about them:
hospital_configs, hospital_prompts, summary_prompt_templates, form_templates,
email_templates, features, execution_logs.

IMPORTANT: every table is ALREADY filtered to the current hospital by the
database — never add a hospital_id filter yourself, and never ask the user for
a hospital id. Join on the FKs above for cross-table questions.

MONEY METRICS — which COLUMN to use (an "amount" is a number to SUM, NOT a status):
- approved / sanctioned amount -> SUM(hospitalization.approved_amount)
  (cumulative pre-auth amount approved by the insurer).
- claimed amount (claim stage) -> SUM(claims.claimed_amount).
- settled / paid amount -> SUM(settlement_item.settled_amount) (NOT the
  deprecated empty `settlements` table). Settlement DATE/insurer/UTR are on
  settlement_batch; for date-filtered settlement questions join
  settlement_item.batch_id -> settlement_batch.id and filter settlement_date.
  FAN-OUT WARNING: settlement_batch is a HEADER (one total_settlement_amount per
  batch) and settlement_item is its LINES. Do NOT join them and SUM
  total_settlement_amount — that multiplies the header by the line count. For a
  settlement total either SUM(settlement_item.settled_amount) (joining batch only
  to filter by date), OR SUM(settlement_batch.total_settlement_amount) from
  settlement_batch ALONE (no join).
- requested / pre-auth / estimated cost -> SUM(pre_auth_stay.total_cost).
- per-round approved amount (one approval event) -> status_history.approved_amount.

The single most important rule: an AMOUNT question means SUM a money column.
A "how many / which cases" question means FILTER by status. Do NOT turn an
amount question into a status filter. For example, "approved amount this month"
is SUM(approved_amount) for cases created this month — it is NOT
WHERE preauth_outcome = 'APPROVED'. Only filter on preauth_outcome / case_status
when the user explicitly asks about case OUTCOMES or COUNTS (e.g. "how many
approved cases").

QUERY RULES — avoid these common mistakes:
- OUTCOMES vs WORKFLOW STATE: pre-auth decision outcomes — APPROVED, DENIED,
  PARTIALLY_APPROVED, ENHANCEMENT_APPROVED/DENIED, CANCELLED — live in
  preauth_outcome. Filter outcome questions ("approved/denied/partially approved
  cases") on preauth_outcome, NOT case_status. case_status holds workflow states
  (DRAFT, SUBMITTED, ENHANCE_SUBMITTED, CLAIM_SUBMITTED, ...); there is NO plain
  'APPROVED' in case_status, so case_status='APPROVED' always returns 0 — wrong.
- COUNTING cases/claims — never fan out through pre_auth: it has MULTIPLE snapshot
  rows per case (one PRE_AUTH and often a CLAIM row), so joining it multiplies
  counts and sums. To count or aggregate cases/claims, query the target table
  directly or use COUNT(DISTINCT claim_case_id) / SUM over distinct cases. Example:
  pre-auths CONVERTED TO CLAIMS = COUNT(DISTINCT claim_case_id) FROM claims (or
  cases having a claims row) — do NOT join pre_auth to claims for this.
- "BY / PER / FOR EACH X" means GROUP BY X — return one row per group, not a
  single total. E.g. "approved amount by insurer" -> JOIN policy_provider_configs
  and GROUP BY the provider name.
- current_stage has ONLY two values: 'PRE_AUTH' and 'CLAIM'. NEVER filter
  current_stage for outcomes or workflow states. Workflow states live in
  case_status. "Awaiting insurer" = case_status IN (SUBMITTED, ENHANCE_SUBMITTED,
  RECONSIDER, ADR_SUBMITTED, CLAIM_SUBMITTED, CLAIM_ADR_SUBMITTED, CLAIM_RECONSIDER).
- pre_auth.status is the FORM state (DRAFT/SUBMITTED) — NEVER use it for pre-auth
  outcomes. Outcomes (APPROVED/DENIED/PARTIALLY_APPROVED/ENHANCEMENT_*) are ALWAYS
  hospitalization.preauth_outcome.
- "Pre-auth requests / pre-auths raised" = pre_auth rows WHERE stage='PRE_AUTH'
  (the table also holds CLAIM-stage rows). Always add stage='PRE_AUTH' when
  counting pre-auths, or count hospitalization cases instead.
- RANKING by a nullable amount (highest/top/max approved_amount etc.): exclude
  NULLs — add "WHERE <col> IS NOT NULL" (or "ORDER BY <col> DESC NULLS LAST"),
  else NULLs sort first and you return an empty/null top row.
- PATIENT NAME lives ONLY in pre_auth_patient.patient_name. Join patients via
  pre_auth_patient.form_data_id -> pre_auth.id (stage='PRE_AUTH') -> hospitalization.id.
  NEVER join uhid = patient_name (uhid is an ID, not a name).

TIME RANGES: "this month" -> created_at >= date_trunc('month', CURRENT_DATE);
"last month", "this year", "today" etc. follow the same date_trunc pattern on
created_at (use hospitalization.created_at unless the question is about a
specific later stage like claims/settlements).\
"""


# Full, ground-truth catalog of every queryable table — columns, types and FKs —
# introspected from the live DB so the planner/executor never guess names. Built
# once and cached (schema is static at runtime); empty string on failure so the
# agent falls back to SCHEMA_GUIDE alone.
_SCHEMA_CATALOG: str | None = None


def _build_schema_catalog() -> str:
    from collections import defaultdict
    from app.db.session import engine

    with engine.connect() as conn:
        cols = conn.execute(
            text(
                "SELECT table_name, column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name = ANY(:t) "
                "ORDER BY table_name, ordinal_position"
            ),
            {"t": ALLOWED_TABLES},
        ).fetchall()
        fks = conn.execute(
            text(
                "SELECT tc.table_name, kcu.column_name, "
                "       ccu.table_name AS ftable, ccu.column_name AS fcol "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name = kcu.constraint_name "
                " AND tc.table_schema = kcu.table_schema "
                "JOIN information_schema.constraint_column_usage ccu "
                "  ON ccu.constraint_name = tc.constraint_name "
                " AND ccu.table_schema = tc.table_schema "
                "WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public' "
                "  AND tc.table_name = ANY(:t)"
            ),
            {"t": ALLOWED_TABLES},
        ).fetchall()

    cols_by: dict[str, list[str]] = defaultdict(list)
    for table, col, dtype in cols:
        cols_by[table].append(f"{col} {dtype}")
    fks_by: dict[str, list[str]] = defaultdict(list)
    for table, col, ftable, fcol in fks:
        fks_by[table].append(f"{col} -> {ftable}.{fcol}")

    out = [
        "FULL TABLE CATALOG — every queryable table with its real columns, types "
        "and foreign keys (ground truth from the live database; use these exact "
        "names, do not invent columns):",
    ]
    for table in ALLOWED_TABLES:
        if table not in cols_by:
            continue
        out.append(f"- {table}({', '.join(cols_by[table])})")
        if fks_by.get(table):
            out.append(f"    FK: {'; '.join(fks_by[table])}")
    return "\n".join(out)


def _schema_catalog() -> str:
    """Cached full-schema catalog; built lazily on first use."""
    global _SCHEMA_CATALOG
    if _SCHEMA_CATALOG is None:
        try:
            _SCHEMA_CATALOG = _build_schema_catalog()
        except Exception as e:  # noqa: BLE001 — degrade to SCHEMA_GUIDE only
            logger.warning("Could not build schema catalog: %s", e)
            _SCHEMA_CATALOG = ""
    return _SCHEMA_CATALOG


def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, UUID):
        return str(o)
    return str(o)


def _build_tools(hospital_id: str, trace: dict):
    """Create the agent's DB tools, bound to one hospital. `trace` collects the
    SQL run and the last result set so the API can surface them."""
    from langchain_core.tools import tool

    @tool
    def list_tables() -> str:
        """List the database tables available to query. Call this first."""
        return ", ".join(ALLOWED_TABLES)

    @tool
    def get_schema(table_names: str) -> str:
        """Return columns (name + type) for one or more comma-separated tables.
        Call before writing SQL so you use real column names."""
        names = [t.strip() for t in table_names.split(",") if t.strip()]
        unknown = [t for t in names if t not in _ALLOWED_SET]
        if unknown:
            return f"Unknown/!allowed tables: {', '.join(unknown)}. Use list_tables."
        out = []
        with readonly_connection(hospital_id) as conn:
            for t in names:
                rows = conn.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name=:t "
                        "ORDER BY ordinal_position"
                    ),
                    {"t": t},
                ).fetchall()
                cols = ", ".join(f"{r[0]} ({r[1]})" for r in rows)
                out.append(f"{t}: {cols}")
        return "\n".join(out)

    @tool
    def run_query(query: str) -> str:
        """Execute a single read-only PostgreSQL SELECT and return up to
        200 rows as JSON. Reject your own DML — only SELECT is allowed."""
        try:
            safe = sql_guard.sanitize(query)
        except sql_guard.SqlGuardError as e:
            return f"Query rejected by safety guard: {e}"
        try:
            with readonly_connection(hospital_id) as conn:
                result = conn.execute(text(safe))
                cols = list(result.keys())
                rows = [dict(zip(cols, r)) for r in result.fetchall()]
        except Exception as e:  # surface DB errors back to the agent to retry
            logger.warning("AI query failed: %s", e)
            return f"Error running query: {str(e)[:400]}"
        # Coerce to JSON-safe primitives (datetime/UUID/Decimal -> str/float) so
        # the rows can both be returned AND persisted to a JSONB column.
        payload = json.dumps(rows, default=_json_default)
        safe_rows = json.loads(payload)
        trace["queries"].append(safe)
        trace["last_columns"] = cols
        trace["last_rows"] = safe_rows
        return payload[:8000]

    @tool
    def check_query(query: str) -> str:
        """Sanity-check a SELECT for obvious mistakes before running it.
        Returns the issues found, or 'OK'."""
        try:
            sql_guard.sanitize(query)
        except sql_guard.SqlGuardError as e:
            return f"Not allowed: {e}"
        return "OK (passes the safety guard — run it with run_query)."

    return [list_tables, get_schema, run_query, check_query]


SYSTEM_PROMPT = f"""You are a data assistant for a hospital administrator using OASYS.
Given a question, you create syntactically correct PostgreSQL SELECT queries,
run them, and answer in clear, human-readable language.

Workflow:
1. Understand what the user is really asking. Map their words to the right
   metric/column using the MONEY METRICS guide below BEFORE writing SQL. A money
   "amount" is a column to SUM, not a status to filter on.
2. Call list_tables to see what exists.
3. Call get_schema for the tables you think are relevant to get exact columns.
4. Write ONE read-only SELECT. Never write INSERT/UPDATE/DELETE or DDL.
5. Optionally check_query, then run_query. If a query errors, read the error and fix it.
6. Answer the user's question based on the rows. Use the data — do not make up numbers.

ASK BEFORE GUESSING: if the question is ambiguous or you don't have enough
information to build a correct query, STOP and ask ONE short clarifying question
instead of guessing or inventing a filter. Ask when you are unsure about:
- which metric/column they mean (e.g. approved vs claimed vs settled amount),
- the time range ("recent", "lately" — over what period?),
- pre-auth stage vs claim stage.
Do not fabricate a WHERE clause to resolve ambiguity — ask the user. When the
question IS clear, just answer it; don't ask unnecessary questions.

PREFER ANSWERING OVER ASKING for a named patient/case. If the user names a
specific patient (or case/claim number) and asks for status/details, DO NOT ask
whether they want "a count" or "details" or which record — just look them up and
SHOW what matches. Match patient names case-insensitively (ILIKE). Then:
- one match  -> give the status/details directly;
- several matches -> list each case with its status and a human identifier
  (e.g. patient name, hospitalisation/created date, claim number) and ask which
  one they mean — i.e. disambiguate by SHOWING the actual cases, never by asking
  an abstract question;
- no match -> say no case was found for that name.

NEVER REVEAL THE DATABASE STRUCTURE. Table names, schemas, column names, raw
SQL, and internal IDs are implementation details — use list_tables/get_schema
ONLY to build your query, never to answer the user. If the user asks what tables
or columns exist, the schema, the data model, or how the data is stored, do NOT
list them. Instead, briefly tell them what they can ask about in plain business
terms — pre-auths, claims, approvals/approved amounts, settlements, providers,
case status — and invite a specific question. Do not echo table or
column names in your answer; refer to things by their business meaning.

Rules:
- Unless asked for a specific count, limit results to at most 50 rows.
- Prefer aggregates (COUNT, SUM, AVG) for "how many"/"total"/"average" questions.
- Format money in Indian rupees (₹) and dates readably.
- If the data can't answer the question, say so plainly.
- Be concise. End with a direct answer, not a description of the SQL.

{SCHEMA_GUIDE}"""


# The planner runs FIRST. It turns the question into a structured plan (or asks
# for clarification) before any SQL is written. This forces the metric->column
# decision up front and makes the "ask when ambiguous" gate deterministic.
PLANNER_PROMPT = f"""You are the PLANNER for a hospital-admin data assistant.
You do NOT write or run SQL. You read the user's question (and recent chat
context) and produce a structured plan that a separate SQL executor will follow.

Decide, using the MONEY METRICS and table guide below:
- What figure/metric is being asked for, and EXACTLY which table.column holds it
  (e.g. "approved amount" -> hospitalization.approved_amount, aggregate SUM).
  An "amount" is a money column to aggregate, NOT a status filter.
- The time range, if any, as a SQL expression on a date column
  (e.g. "this month" -> created_at >= date_trunc('month', CURRENT_DATE)).
- Any named filters (patient, provider, status) as entities.
- Which tables to read and the FK joins needed.
- The ordered steps the executor should take (get_schema, then run_query, ...).

CLARIFY WHEN UNSURE: if you cannot confidently map the question to a metric,
column, time range, or stage — or it is otherwise ambiguous — set
needs_clarification=true and give ONE short clarifying_question. Do NOT guess a
column or invent a filter. When the question is clear, set
needs_clarification=false and fill in the plan. Note: data is already scoped to
the user's hospital — never treat a missing hospital as ambiguity.

NAMED PATIENT/CASE LOOKUPS are NOT ambiguous — do not clarify them. If the user
names a specific patient (or case/claim number) and asks for status/details, set
needs_clarification=false and plan to RETRIEVE the matching record(s): match the
patient name case-insensitively (ILIKE) and select each case with its status and
identifying fields (date, claim number) so the executor can list them and let the
user pick if there is more than one. Never ask "do you want a count or details".

NEVER EXPOSE DB STRUCTURE: table names, schemas, column names and internal IDs
are internal. If the user asks what tables/columns exist, the schema, or how data
is stored, that is a meta request — set needs_clarification=false, intent
"meta_schema_request", leave metric/time_range/tables/joins/steps empty, and let
the executor reply in business terms. Never put table or column names in a
clarifying_question.

{SCHEMA_GUIDE}"""


def _format_plan(plan: QueryPlan) -> str:
    """Render an approved plan as a compact instruction block for the executor."""
    lines = [f"Intent: {plan.intent or 'n/a'}"]
    if plan.metric:
        lines.append(
            f"Metric: {plan.metric.term} -> {plan.metric.aggregate}({plan.metric.column})"
        )
    if plan.time_range:
        lines.append(f"Time range: {plan.time_range.phrase} -> {plan.time_range.expr}")
    if plan.entities:
        lines.append(
            "Filters: " + ", ".join(f"{e.type}={e.value}" for e in plan.entities)
        )
    if plan.tables:
        lines.append("Tables: " + ", ".join(plan.tables))
    if plan.joins:
        lines.append("Joins: " + "; ".join(plan.joins))
    if plan.steps:
        lines.append("Steps:")
        for s in plan.steps:
            dep = f" (after {s.depends_on})" if s.depends_on else ""
            lines.append(f"  {s.n}. {s.action} — {s.purpose}{dep}")
    return "\n".join(lines)


# Deterministic guard: questions about the DB structure itself must never reach
# the executor (which now carries the full table catalog and would happily list
# it). We answer these in business terms in code and skip the agent entirely.
_META_SCHEMA_REPLY = (
    "I can answer questions about your hospital's data — pre-auths, claims, "
    "approvals and approved amounts, settlements, providers, and case "
    "status. I can't share the database's internal structure, but ask me anything "
    "specific, e.g. \"how many pre-auths this month\" or \"total approved amount "
    "this year\"."
)
_SCHEMA_WORDS = re.compile(
    r"\b(tables?|schemas?|columns?|fields?|database structure|data ?model|"
    r"db structure|table names?|column names?)\b",
    re.IGNORECASE,
)


def _is_meta_schema_request(plan: QueryPlan, question: str) -> bool:
    """True if the user is asking about the DB structure, not their data.

    Driven by keywords in the QUESTION (deterministic) rather than the planner's
    intent label — the planner over-applies "meta_schema_request" to vague
    questions (e.g. "show me recent activity"), which then got wrongly refused.
    """
    q = question.lower()
    return bool(_SCHEMA_WORDS.search(q)
                and re.search(r"\b(list|show|what|which|all|name|see|view|describe|have|has)\b", q))


def _meta_schema_result() -> dict:
    return {"answer": _META_SCHEMA_REPLY, "sql": [], "columns": [], "rows": [],
            "plan": {"needs_clarification": False, "intent": "meta_schema_request"}}


def _planner_system_prompt() -> str:
    return PLANNER_PROMPT + "\n\n" + _schema_catalog()


def _executor_system_prompt() -> str:
    return SYSTEM_PROMPT + "\n\n" + _schema_catalog()


async def _plan(model, question: str, history: list[dict] | None) -> QueryPlan:
    """Run the planner and return a validated QueryPlan."""
    planner = model.with_structured_output(QueryPlan)
    messages = [{"role": "system", "content": _planner_system_prompt()}]
    messages += [
        {"role": m["role"], "content": m["content"]}
        for m in (history or [])
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    messages.append({"role": "user", "content": question})
    return await planner.ainvoke(messages)


def _extract_text(content) -> str:
    """Flatten a message's content (str or provider content-blocks) to text."""
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        ).strip()
    return content or ""


def _exec_messages(question: str, history: list[dict] | None, plan: QueryPlan) -> list[dict]:
    """Build the executor's message list: prior turns, the question, then the plan."""
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in (history or [])
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    messages.append({"role": "user", "content": question})
    messages.append({
        "role": "user",
        "content": (
            "APPROVED PLAN — follow it. Use get_schema to confirm real column "
            "names before run_query; correct the plan if a column doesn't exist.\n"
            + _format_plan(plan)
        ),
    })
    return messages


def _error_detail(exc: Exception) -> str:
    """Map an LLM/agent exception to a clean, user-safe message."""
    text_ = str(exc)
    if exc.__class__.__name__ == "RateLimitError" or "insufficient_quota" in text_:
        return "The AI assistant is temporarily unavailable (API quota exceeded)."
    return "The assistant couldn't answer that. Please rephrase and try again."


async def astream_answer(hospital_id: str, question: str,
                         history: list[dict] | None = None):
    """Streaming variant of answer_question. Yields SSE-ready event dicts
    ({"event": str, "data": dict}) as the work progresses, so the HTTP
    connection keeps producing bytes and never hits an idle timeout.

    Event types: status, plan, clarification, step, done, error.
    The final `done` event carries the same payload answer_question returns.
    """
    from langchain.agents import create_agent
    from langchain.chat_models import init_chat_model

    if not settings.OPENAI_API_KEY:
        yield {"event": "error", "data": {"detail": "OPENAI_API_KEY is not configured."}}
        return

    trace = {"queries": [], "last_columns": [], "last_rows": []}
    model = init_chat_model(
        settings.AI_QUERY_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=0,
    )

    # Step 1 — PLAN.
    yield {"event": "status", "data": {"stage": "planning"}}
    try:
        plan = await _plan(model, question, history)
    except Exception as e:  # noqa: BLE001
        logger.exception("AI planner failed")
        yield {"event": "error", "data": {"detail": _error_detail(e)}}
        return

    # Schema/meta requests never reach the executor — answer in business terms.
    if _is_meta_schema_request(plan, question):
        yield {"event": "done", "data": _meta_schema_result()}
        return

    if plan.needs_clarification:
        msg = plan.clarifying_question or "Could you clarify what you'd like to know?"
        yield {"event": "clarification", "data": {"question": msg}}
        yield {"event": "done", "data": {
            "answer": msg, "sql": [], "columns": [], "rows": [], "plan": plan.model_dump(),
        }}
        return

    yield {"event": "plan", "data": plan.model_dump()}

    # Step 2 — EXECUTE, streaming one heartbeat per agent step.
    agent = create_agent(model, _build_tools(hospital_id, trace),
                         system_prompt=_executor_system_prompt())
    yield {"event": "status", "data": {"stage": "executing"}}

    answer = ""
    try:
        async for update in agent.astream(
            {"messages": _exec_messages(question, history, plan)},
            {"recursion_limit": 25},
            stream_mode="updates",
        ):
            for _node, payload in (update or {}).items():
                msgs = payload.get("messages", []) if isinstance(payload, dict) else []
                for m in msgs:
                    tool_calls = getattr(m, "tool_calls", None)
                    mtype = getattr(m, "type", "")
                    if tool_calls:
                        for tc in tool_calls:
                            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                            yield {"event": "step", "data": {"action": name, "status": "running"}}
                    elif mtype == "tool":
                        yield {"event": "step",
                               "data": {"action": getattr(m, "name", "query"), "status": "done"}}
                    elif mtype == "ai":
                        text_ = _extract_text(getattr(m, "content", ""))
                        if text_:
                            answer = text_  # last non-tool-call AI message is the answer
    except Exception as e:  # noqa: BLE001
        logger.exception("AI executor failed")
        yield {"event": "error", "data": {"detail": _error_detail(e)}}
        return

    yield {"event": "done", "data": {
        "answer": answer or "I couldn't produce an answer.",
        "sql": trace["queries"],
        "columns": trace["last_columns"],
        "rows": trace["last_rows"],
        "plan": plan.model_dump(),
    }}


async def answer_question(hospital_id: str, question: str,
                          history: list[dict] | None = None) -> dict:
    """Run the agent for one question. Returns {answer, sql, columns, rows}.

    `history` is an optional list of prior turns ({"role": "user"|"assistant",
    "content": str}) used as conversational context for follow-up questions.
    """
    from langchain.agents import create_agent
    from langchain.chat_models import init_chat_model

    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    trace = {"queries": [], "last_columns": [], "last_rows": []}
    model = init_chat_model(
        settings.AI_QUERY_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=0,
    )

    # Step 1 — PLAN. Decide the metric/columns/range, or ask for clarification.
    plan = await _plan(model, question, history)

    # Schema/meta requests never reach the executor — answer in business terms.
    if _is_meta_schema_request(plan, question):
        return _meta_schema_result()

    # If the planner can't answer confidently, return its question — no DB hit.
    if plan.needs_clarification:
        return {
            "answer": plan.clarifying_question
            or "Could you clarify what you'd like to know?",
            "sql": [],
            "columns": [],
            "rows": [],
            "plan": plan.model_dump(),
        }

    # Step 2 — EXECUTE. Run the SQL agent, handing it the approved plan.
    agent = create_agent(
        model,
        _build_tools(hospital_id, trace),
        system_prompt=_executor_system_prompt(),
    )

    result = await agent.ainvoke(
        {"messages": _exec_messages(question, history, plan)},
        # Bound the ReAct loop so a confused agent can't run forever.
        {"recursion_limit": 25},
    )
    final = result["messages"][-1]
    answer = _extract_text(getattr(final, "content", "")) or "I couldn't produce an answer."

    return {
        "answer": answer,
        "sql": trace["queries"],
        "columns": trace["last_columns"],
        "rows": trace["last_rows"],
        "plan": plan.model_dump(),
    }
