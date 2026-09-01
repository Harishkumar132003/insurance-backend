"""SQL generation, guarding and execution against the Cube SQL API.

The guard is not decoration. Three Cube SQL behaviours were verified directly against
the live instance and each one silently produces a WRONG ANSWER rather than an error:

    SELECT total_preauth_count FROM preauth_tat_workflow
        -> 29 rows of `1`, not the count 29.
    SELECT COUNT(*) FROM master_hospital_360
        -> 172, because the view fans out; the true pre-auth count is 29.
    SELECT is_preauth_denied, MEASURE(...) ... GROUP BY 1
        -> the segment column comes back NULL.

A prompt rule alone will not hold the line on any of these, so `guard_sql` rejects them
in code and the rejection is fed back through the repair loop.
"""
import asyncio
import time

import sqlglot
from sqlglot import exp

from app.core.config import settings
from app.schemas.hybrid import GeneratedSql, MemberSelection
from app.services.hybrid.common import chat_model, log, short
from app.services.hybrid.cube_meta import Member, by_qname, render_menu
from app.services.hybrid.diagnostics import empty_result_hint
from app.services.hybrid.prompts import (
    CUBE_SQL_PROMPT,
    EMPTY_RESULT_REPAIR_PROMPT,
    SQL_REPAIR_PROMPT,
)

MAX_ROWS = 500
# Three failure classes now share this budget: guard rejection, execution error,
# and a zero-row result. One repair left the third class with nothing to spend.
MAX_REPAIRS = 2

_FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
              exp.Alter, exp.Merge, exp.Command)


class SqlGuardError(Exception):
    pass


# ---- helpers for the ranking check ----------------------------------------
def _measures_in(node, measures: set[str]) -> set[str]:
    """Measure names referenced anywhere under a node."""
    if node is None:
        return set()
    return {c.name for c in node.find_all(exp.Column) if c.name in measures}


def _ranked_measures(tree: exp.Select, ordered: exp.Ordered, measures: set[str]) -> set[str]:
    """Which measures an ORDER BY term actually ranks on.

    Resolves the three ways a measure reaches ORDER BY: written out as
    MEASURE(x), referenced by its SELECT alias, or by ordinal position.
    """
    target = ordered.this

    # ORDER BY 2  ->  the second projection
    if isinstance(target, exp.Literal) and target.is_int:
        idx = int(target.name) - 1
        projections = tree.expressions
        return _measures_in(projections[idx], measures) if 0 <= idx < len(projections) else set()

    # ORDER BY <alias>  ->  the projection carrying that alias
    if isinstance(target, exp.Column):
        name = target.name
        if name in measures:
            return {name}
        for e in tree.expressions:
            if isinstance(e, exp.Alias) and e.alias == name:
                return _measures_in(e, measures)
        return set()

    # ORDER BY MEASURE(x)
    return _measures_in(target, measures)


def _duplicate_projected_measures(tree: exp.Select, measures: set[str]) -> set[str]:
    """Measures projected as a whole column more than once.

    Deliberately scoped to projections that are exactly `MEASURE(x)`, aliased or not.
    A measure appearing twice INSIDE one expression is legitimate — a ratio like
    `MEASURE(approved) / MEASURE(raised)` reuses nothing wrongly — and must not trip.
    """
    counts: dict[str, int] = {}
    for e in tree.expressions:
        node = e.this if isinstance(e, exp.Alias) else e
        if not (isinstance(node, exp.Anonymous) and (node.this or "").upper() == "MEASURE"):
            continue
        cols = list(node.find_all(exp.Column))
        if len(cols) == 1 and cols[0].name in measures:
            counts[cols[0].name] = counts.get(cols[0].name, 0) + 1
    return {name for name, n in counts.items() if n > 1}


# ---- generation ------------------------------------------------------------
def build_menu(view: str, selection: MemberSelection, catalog: list[Member]) -> str:
    """Only the selected members, rendered by kind. A tight menu is the whole point of
    having retrieved and re-ranked."""
    index = by_qname(catalog)
    from app.services.hybrid.retrieval import selected_qnames

    members = [index[q] for q in selected_qnames(selection) if q in index]
    # Re-point onto the derived view; the shortlist may have come from other views.
    view_index = {m.name: m for m in catalog if m.view == view}
    resolved, missing = [], []
    for m in members:
        hit = view_index.get(m.name)
        (resolved if hit else missing).append(hit or m.qname)
    if missing:
        log("menu", "%d selected member(s) not on %s: %s", len(missing), view, missing)
    return render_menu(resolved)


async def generate_sql(question: str, menu: str, view: str, entity_hint: str) -> str:
    from datetime import date

    structured = chat_model(GeneratedSql, sql=True)
    system = CUBE_SQL_PROMPT.format(view=view, today=date.today().isoformat())
    user_parts = [f"QUESTION: {question}", "", "AVAILABLE FIELDS:", menu]
    if entity_hint:
        user_parts += ["", entity_hint]
    out: GeneratedSql = await structured.ainvoke([
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ])
    sql = _strip(out.sql)
    log("gen-sql", "%s", sql)
    return sql


async def repair_sql(question: str, menu: str, view: str, entity_hint: str,
                     bad_sql: str, error: str,
                     template: str = SQL_REPAIR_PROMPT) -> str:
    """Ask for a corrected query. `template` selects the framing: SQL_REPAIR_PROMPT
    when the statement errored, EMPTY_RESULT_REPAIR_PROMPT when it ran but matched
    nothing — telling a model to "fix the SQL so it runs" when it already ran is how
    you get a working query rewritten into a broken one."""
    from datetime import date

    structured = chat_model(GeneratedSql, sql=True)
    system = CUBE_SQL_PROMPT.format(view=view, today=date.today().isoformat())
    user_parts = [f"QUESTION: {question}", "", "AVAILABLE FIELDS:", menu]
    if entity_hint:
        user_parts += ["", entity_hint]
    user_parts += ["", template.format(sql=bad_sql, error=short(error, 1500))]
    out: GeneratedSql = await structured.ainvoke([
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ])
    sql = _strip(out.sql)
    log("repair", "%s", sql)
    return sql


def _strip(sql: str) -> str:
    sql = (sql or "").strip()
    if sql.startswith("```"):
        sql = sql.split("```")[1] if "```" in sql[3:] else sql[3:]
        sql = sql.removeprefix("sql").strip()
    return sql.strip().rstrip(";").strip()


# ---- guard -----------------------------------------------------------------
def guard_sql(sql: str, view: str, catalog: list[Member],
              hospital_id: str | None = None, max_rows: int = MAX_ROWS) -> tuple[str, dict]:
    """Validate against the Cube catalog (NOT Postgres — 5 of the 8 views have no
    physical table), enforce the MEASURE()/COUNT(*)/segment rules, then inject the
    tenant filter and a row cap."""
    statements = [s for s in sqlglot.parse(sql, read="postgres") if s]
    if len(statements) != 1:
        raise SqlGuardError("expected exactly one statement")
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise SqlGuardError("only a single SELECT is allowed")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN):
            raise SqlGuardError(f"forbidden statement: {type(node).__name__}")

    tables = {t.name for t in tree.find_all(exp.Table)}
    if tables - {view}:
        raise SqlGuardError(f"only '{view}' may be queried; blocked {sorted(tables - {view})}")

    view_members = {m.name: m for m in catalog if m.view == view}
    measures = {n for n, m in view_members.items() if m.kind == "measure"}
    segments = {n for n, m in view_members.items() if m.kind == "segment"}
    aliases = {a.alias for a in tree.find_all(exp.Alias) if a.alias}

    # Unknown columns — the error names them so the repair pass can fix it.
    unknown = sorted({
        c.name for c in tree.find_all(exp.Column)
        if c.name and c.name not in view_members and c.name not in aliases
        and c.name != "hospital_id"
    })
    if unknown:
        raise SqlGuardError(
            f"unknown column(s) {unknown} on view '{view}'. Valid fields: "
            f"{sorted(view_members)[:40]}")

    # COUNT(*) counts fanned-out join rows, not entities.
    for cnt in tree.find_all(exp.Count):
        if isinstance(cnt.this, exp.Star):
            raise SqlGuardError(
                "COUNT(*) is not allowed — it counts joined rows and over-counts. "
                f"Use MEASURE(<count measure>) instead, e.g. "
                f"{sorted(n for n in measures if n.endswith('_count'))[:3]}")

    # Every measure must sit inside MEASURE(). A bare one returns per-row 1s silently.
    wrapped = {
        col.name
        for fn in tree.find_all(exp.Anonymous)
        if (fn.this or "").upper() == "MEASURE"
        for col in fn.find_all(exp.Column)
    }
    bare = sorted({
        c.name for c in tree.find_all(exp.Column)
        if c.name in measures and c.name not in wrapped
    })
    if bare:
        raise SqlGuardError(
            f"measure(s) {bare} must be wrapped in MEASURE(...). A bare measure returns "
            f"one row per record instead of the aggregate. Write MEASURE({bare[0]}).")

    # The same measure projected twice under two aliases. Never something a real answer
    # needs — it is the fingerprint of a generator that was one measure short and padded
    # the gap. "Pre-auth vs claim turnaround" produced exactly this, and the duplicated
    # column was then reported as the missing one's value, so the two read as equal.
    dup = sorted(_duplicate_projected_measures(tree, measures))
    if dup:
        m = dup[0]
        raise SqlGuardError(
            f"measure(s) {dup} projected more than once under different aliases. Two "
            f"columns holding the same number cannot answer a comparison. Use the "
            f"distinct measure each column is meant to report — if the other one is not "
            f"on this view, drop the column rather than repeating MEASURE({m}).")

    # Segments only work in WHERE; in SELECT/GROUP BY they come back NULL.
    projection_cols = {c.name for e in tree.expressions for c in e.find_all(exp.Column)}
    group = tree.args.get("group")
    if group:
        projection_cols |= {c.name for c in group.find_all(exp.Column)}
    bad_segments = sorted(projection_cols & segments)
    if bad_segments:
        raise SqlGuardError(
            f"segment(s) {bad_segments} cannot appear in SELECT or GROUP BY — they "
            f"return NULL there. Use them only in WHERE, e.g. WHERE {bad_segments[0]} = true.")

    # "Top N by <measure>" without a floor on that measure. On DESC, Cube sorts NULLs
    # FIRST, so the winner is a record that has no value at all — a silent wrong answer,
    # not an error. NULLS LAST does not rescue it: Cube accepts the clause and ignores
    # it (verified). Only HAVING actually filters the empty rows out.
    order = tree.args.get("order")
    if order is not None and tree.args.get("limit"):
        guarded = _measures_in(tree.args.get("having"), measures)
        for ordered in order.expressions:
            if not ordered.args.get("desc"):
                continue
            unguarded = _ranked_measures(tree, ordered, measures) - guarded
            if unguarded:
                m = sorted(unguarded)[0]
                raise SqlGuardError(
                    f"ranking by measure '{m}' with a LIMIT but no HAVING floor. Rows with "
                    f"no value sort FIRST on DESC, so this returns records where '{m}' is "
                    f"empty. NULLS LAST does NOT fix this — the Cube SQL API ignores it. "
                    f"Add: HAVING MEASURE({m}) > 0")

    info: dict = {"rls_applied": False, "limit_applied": None}

    if hospital_id:
        if "hospital_id" in view_members or True:  # every view exposes hospital_id
            safe = str(hospital_id).replace("'", "''")
            tree = tree.where(exp.condition(f"hospital_id = '{safe}'"))
            info["rls_applied"] = True

    if not tree.args.get("limit"):
        tree = tree.limit(max_rows)
        info["limit_applied"] = max_rows

    return tree.sql(dialect="postgres"), info


# ---- execution -------------------------------------------------------------
def _run_blocking(sql: str, params: tuple | None = None) -> tuple[list, list]:
    import psycopg2

    conn = psycopg2.connect(
        host=settings.CUBE_SQL_HOST, port=settings.CUBE_SQL_PORT,
        dbname=settings.CUBE_SQL_DB, user=settings.CUBE_SQL_USER,
        password=settings.CUBE_SQL_PASSWORD, connect_timeout=10,
    )
    try:
        cur = conn.cursor()
        cur.execute(sql, params) if params else cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(cols, r)) for r in cur.fetchall()] if cols else []
        cur.close()
        return cols, rows
    finally:
        conn.close()


async def run_cube_sql(sql: str, params: tuple | None = None) -> tuple[list, list]:
    """Run one statement. `params` binds through psycopg2 for code-issued SQL; the
    model-written path passes None because guard_sql has already vetted the literal."""
    t0 = time.perf_counter()
    cols, rows = await asyncio.to_thread(_run_blocking, sql, params)
    log("execute", "%d rows, cols=%s (%dms)", len(rows), cols,
        int((time.perf_counter() - t0) * 1000))
    return cols, rows


async def ping() -> bool:
    try:
        await asyncio.to_thread(_run_blocking, "SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- generate -> guard -> execute, with one repair -------------------------
async def generate_guard_execute(question: str, menu: str, view: str, catalog: list[Member],
                                 entity_hint: str = "", hospital_id: str | None = None,
                                 execute: bool = True) -> dict:
    """Returns {ok, sql, columns, rows, attempts, guard}. The repair pass is what the
    production pipeline has but can never reach."""
    attempts: list[dict] = []
    sql = await generate_sql(question, menu, view, entity_hint)
    guard: dict = {}
    # One shot only. A question whose honest answer IS "no rows" must not loop, and a
    # second diagnosis of the same empty result would say the same thing anyway.
    empty_repair_used = False

    for attempt in range(MAX_REPAIRS + 1):
        record: dict = {"attempt": attempt + 1, "raw_sql": sql}
        try:
            safe, guard = guard_sql(sql, view, catalog, hospital_id)
            record["guarded_sql"] = safe
        except Exception as e:  # noqa: BLE001
            record["guard_error"] = str(e)
            attempts.append(record)
            log("guard", "REJECTED | %s", short(str(e), 200))
            if attempt == MAX_REPAIRS:
                return {"ok": False, "stage": "guard", "sql": sql, "error": str(e),
                        "attempts": attempts, "guard": guard}
            sql = await repair_sql(question, menu, view, entity_hint, sql, str(e))
            continue

        if not execute:
            attempts.append(record)
            return {"ok": True, "sql": safe, "columns": [], "rows": [],
                    "attempts": attempts, "guard": guard, "executed": False}

        try:
            cols, rows = await run_cube_sql(safe)

            # A clean run that matched nothing is the last silent-wrong-answer path:
            # it reaches the user as a confident "no matching records were found".
            # Only retry when the diagnosis has something concrete to say — an
            # unexplained empty result is more likely to be the true answer.
            if not rows and not empty_repair_used and attempt < MAX_REPAIRS:
                hint = empty_result_hint(safe, view, catalog)
                if hint:
                    empty_repair_used = True
                    record["empty_result_hint"] = hint
                    record["row_count"] = 0
                    attempts.append(record)
                    log("execute", "0 rows | %s", short(hint, 200))
                    sql = await repair_sql(question, menu, view, entity_hint, safe,
                                           hint, template=EMPTY_RESULT_REPAIR_PROMPT)
                    continue

            record["row_count"] = len(rows)
            attempts.append(record)
            return {"ok": True, "sql": safe, "columns": cols, "rows": rows,
                    "attempts": attempts, "guard": guard, "executed": True}
        except Exception as e:  # noqa: BLE001
            record["execute_error"] = str(e)
            attempts.append(record)
            log("execute", "FAILED | %s", short(str(e), 200))
            if attempt == MAX_REPAIRS:
                return {"ok": False, "stage": "execute", "sql": safe, "error": str(e),
                        "attempts": attempts, "guard": guard}
            sql = await repair_sql(question, menu, view, entity_hint, safe, str(e))

    return {"ok": False, "stage": "execute", "sql": sql, "error": "exhausted retries",
            "attempts": attempts, "guard": guard}
