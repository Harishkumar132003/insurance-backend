"""Static guard for agent-generated SQL.

This is the *second* line of defence (the first is the read-only role + RLS in
the database). The LLM is instructed to emit a single read-only SELECT, but we
never trust that — we validate the text in code before it ever reaches the
database, and force a row cap.

The guard is intentionally strict and allowlist-based: anything that is not a
single SELECT / WITH...SELECT statement is rejected.
"""

import re

MAX_ROWS = 200

# Statements / keywords that must never appear — writes, DDL, privilege
# changes, and anything that can run a second command.
_FORBIDDEN = re.compile(
    r"\b("
    r"insert|update|delete|truncate|drop|alter|create|replace|merge|upsert|"
    r"grant|revoke|comment|copy|vacuum|analyze|cluster|reindex|refresh|"
    r"call|do|execute|prepare|deallocate|listen|notify|lock|"
    r"set|reset|begin|commit|rollback|savepoint|"
    r"pg_sleep|pg_read_file|pg_ls_dir|lo_import|lo_export|dblink|copy_from"
    r")\b",
    re.IGNORECASE,
)


class SqlGuardError(ValueError):
    """Raised when generated SQL fails validation."""


def _strip_comments(sql: str) -> str:
    # Remove -- line comments and /* */ block comments so they can't hide
    # forbidden tokens or a second statement.
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def sanitize(sql: str) -> str:
    """Validate `sql` and return a safe, row-limited query.

    Raises SqlGuardError if the statement is anything other than a single
    read-only SELECT (optionally a leading CTE).
    """
    if not sql or not sql.strip():
        raise SqlGuardError("Empty query.")

    cleaned = _strip_comments(sql).strip().rstrip(";").strip()

    if not cleaned:
        raise SqlGuardError("Query is empty after stripping comments.")

    # Exactly one statement — no stacked queries.
    if ";" in cleaned:
        raise SqlGuardError("Multiple statements are not allowed.")

    lowered = cleaned.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise SqlGuardError("Only SELECT queries are allowed.")

    # A leading CTE (WITH) is fine, but it must ultimately be a read — and a
    # WITH ... ( ... INSERT/UPDATE/DELETE ... ) data-modifying CTE is not. The
    # forbidden-keyword scan below catches those.
    if _FORBIDDEN.search(cleaned):
        raise SqlGuardError(
            "Query contains a disallowed keyword. Only read-only SELECTs are permitted."
        )

    # Force a row cap. If the model already wrote a LIMIT, respect the smaller.
    limit_match = re.search(r"\blimit\s+(\d+)\b", lowered)
    if limit_match:
        existing = int(limit_match.group(1))
        if existing > MAX_ROWS:
            cleaned = re.sub(
                r"\blimit\s+\d+\b",
                f"LIMIT {MAX_ROWS}",
                cleaned,
                count=1,
                flags=re.IGNORECASE,
            )
    else:
        cleaned = f"{cleaned}\nLIMIT {MAX_ROWS}"

    return cleaned
