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
a hospital id. Join on the FKs above for cross-table questions.\
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
        trace["queries"].append(safe)
        trace["last_columns"] = cols
        trace["last_rows"] = rows
        return json.dumps(rows, default=_json_default)[:8000]

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
1. Call list_tables to see what exists.
2. Call get_schema for the tables you think are relevant to get exact columns.
3. Write ONE read-only SELECT. Never write INSERT/UPDATE/DELETE or DDL.
4. Optionally check_query, then run_query. If a query errors, read the error and fix it.
5. Answer the user's question based on the rows. Use the data — do not make up numbers.

Rules:
- Unless asked for a specific count, limit results to at most 50 rows.
- Prefer aggregates (COUNT, SUM, AVG) for "how many"/"total"/"average" questions.
- Format money in Indian rupees (₹) and dates readably.
- If the data can't answer the question, say so plainly.
- Be concise. End with a direct answer, not a description of the SQL.

{SCHEMA_GUIDE}"""


async def answer_question(hospital_id: str, question: str) -> dict:
    """Run the agent for one question. Returns {answer, sql, columns, rows}."""
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
    agent = create_agent(
        model,
        _build_tools(hospital_id, trace),
        system_prompt=SYSTEM_PROMPT,
    )

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
        # Bound the ReAct loop so a confused agent can't run forever.
        {"recursion_limit": 25},
    )
    final = result["messages"][-1]
    answer = getattr(final, "content", "") or "I couldn't produce an answer."
    if isinstance(answer, list):  # some providers return content blocks
        answer = " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in answer
        ).strip()

    return {
        "answer": answer,
        "sql": trace["queries"],
        "columns": trace["last_columns"],
        "rows": trace["last_rows"],
    }
