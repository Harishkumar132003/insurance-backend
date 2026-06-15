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
    "claims", "settlements", "invoice", "invoice_payment", "status_history",
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
- settlements — final settlement, FK claim_id -> claims.id.
- invoice / invoice_payment — insurer invoices and payments
  (invoice.claim_case_id -> hospitalization.id; invoice_payment.invoice_id -> invoice.id).
- status_history — audit timeline of status changes, FK claim_case_id.
- query_logs — ADR / "need more info" requests, FK claim_case_id.
- claim_case_emails / _attachments / claim_case_documents / part_d_letters — case correspondence & docs.
- policy_provider_configs — insurers/TPAs (provider names), joined via
  hospitalization.policy_provider_id.

IMPORTANT: every table is ALREADY filtered to the current hospital by the
database — never add a hospital_id filter yourself, and never ask the user for
a hospital id. Join on the FKs above for cross-table questions.

MONEY METRICS — which COLUMN to use (an "amount" is a number to SUM, NOT a status):
- approved / sanctioned amount -> SUM(hospitalization.approved_amount)
  (cumulative pre-auth amount approved by the insurer).
- claimed amount (claim stage) -> SUM(claims.claimed_amount).
- settled / paid amount -> SUM(settlements.settled_amount).
- requested / pre-auth / estimated cost -> SUM(pre_auth_stay.total_cost).
- per-round approved amount (one approval event) -> status_history.approved_amount.

The single most important rule: an AMOUNT question means SUM a money column.
A "how many / which cases" question means FILTER by status. Do NOT turn an
amount question into a status filter. For example, "approved amount this month"
is SUM(approved_amount) for cases created this month — it is NOT
WHERE preauth_outcome = 'APPROVED'. Only filter on preauth_outcome / case_status
when the user explicitly asks about case OUTCOMES or COUNTS (e.g. "how many
approved cases").

TIME RANGES: "this month" -> created_at >= date_trunc('month', CURRENT_DATE);
"last month", "this year", "today" etc. follow the same date_trunc pattern on
created_at (use hospitalization.created_at unless the question is about a
specific later stage like claims/settlements).\
"""


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
- pre-auth stage vs claim stage,
- which provider/insurer/status they mean.
Do not fabricate a WHERE clause to resolve ambiguity — ask the user. When the
question IS clear, just answer it; don't ask unnecessary questions.

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


async def _plan(model, question: str, history: list[dict] | None) -> QueryPlan:
    """Run the planner and return a validated QueryPlan."""
    planner = model.with_structured_output(QueryPlan)
    messages = [{"role": "system", "content": PLANNER_PROMPT}]
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

    if plan.needs_clarification:
        msg = plan.clarifying_question or "Could you clarify what you'd like to know?"
        yield {"event": "clarification", "data": {"question": msg}}
        yield {"event": "done", "data": {
            "answer": msg, "sql": [], "columns": [], "rows": [], "plan": plan.model_dump(),
        }}
        return

    yield {"event": "plan", "data": plan.model_dump()}

    # Step 2 — EXECUTE, streaming one heartbeat per agent step.
    agent = create_agent(model, _build_tools(hospital_id, trace), system_prompt=SYSTEM_PROMPT)
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
        system_prompt=SYSTEM_PROMPT,
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
