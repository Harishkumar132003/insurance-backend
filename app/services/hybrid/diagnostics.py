"""Why did that query return nothing?

`guard_sql` validates the QUERY. This validates the RESULT — specifically the case
where the SQL is syntactically perfect, runs cleanly, and returns zero rows because a
filter value is wrong. That path currently reaches the user as a confident "no matching
records were found", which is the worst failure mode available: a wrong answer wearing
the costume of a right one.

The diagnosis costs no database round trip. The Cube YAML already spells out the value
domains in its descriptions ("Complete set of possible values: DRAFT ...; SUBMITTED,
... CANCELLED; and UNKNOWN"), and the catalog carries those descriptions, so a literal
that isn't in the domain can be caught by string comparison alone.

Returns None whenever it cannot say something concrete. A vague hint is worse than no
hint: it burns a repair round to tell the model what it already knows.
"""
import logging
import re

import sqlglot
from sqlglot import exp

logger = logging.getLogger("app.hybrid")

# Only mine a description for values when it announces that it is enumerating them.
# Without this gate, every "ADR / NMI" and "UTR" in ordinary prose becomes a fake
# domain value and the hints turn into noise.
_DOMAIN_MARKERS = (
    "possible values", "complete set", "valid values", "one of:",
    "values are", "values:",
)

# Enum values in these descriptions are always SCREAMING_SNAKE.
_ENUM_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*\b")

# Tokens that match the shape but are prose, not data.
_ENUM_STOPWORDS = frozenset({
    "ADR", "NMI", "TAT", "UTR", "INR", "SQL", "NULL", "AND", "OR", "NOT",
    "USE", "THE", "FOR", "ALL", "ANY", "PRE", "AUTH", "ID", "FK", "PK",
})

MAX_LISTED_VALUES = 20


def _literal_filters(tree: exp.Expression) -> list[tuple[str, str]]:
    """Every `column <op> 'literal'` pair in the statement, as (column, literal).

    Covers =, LIKE and ILIKE; IN lists are expanded to one pair per element. The
    comparison may be written either way round, so both sides are checked.
    """
    pairs: list[tuple[str, str]] = []

    def _pair(left, right):
        if isinstance(left, exp.Column) and isinstance(right, exp.Literal) and right.is_string:
            pairs.append((left.name, right.this))
        elif isinstance(right, exp.Column) and isinstance(left, exp.Literal) and left.is_string:
            pairs.append((right.name, left.this))

    for node in tree.find_all(exp.EQ, exp.Like, exp.ILike):
        _pair(node.this, node.expression)

    for node in tree.find_all(exp.In):
        col = node.this
        if isinstance(col, exp.Column):
            for item in node.expressions:
                if isinstance(item, exp.Literal) and item.is_string:
                    pairs.append((col.name, item.this))

    # Preserve order, drop duplicates.
    return list(dict.fromkeys(pairs))


def value_domain(description: str) -> tuple[str, ...]:
    """The enumerated values a description advertises, or () if it advertises none."""
    if not description:
        return ()
    low = description.lower()
    if not any(marker in low for marker in _DOMAIN_MARKERS):
        return ()

    values = [t for t in _ENUM_TOKEN.findall(description)
              if t not in _ENUM_STOPWORDS and len(t) > 2]
    return tuple(dict.fromkeys(values))


def _segment_encoding(view_members: dict, column: str, value: str) -> str | None:
    """A segment whose SQL already encodes `column = value`.

    Steering the model onto a segment is strictly better than steering it onto a
    literal: a segment is a filter the team wrote and reviewed.
    """
    needle = value.strip().upper()
    for name, m in view_members.items():
        if m.kind != "segment":
            continue
        haystack = f"{name} {m.title} {m.description}".upper()
        if needle and needle in haystack and column.upper() in haystack:
            return name
    return None


def empty_result_hint(sql: str, view: str, catalog: list) -> str | None:
    """Explain a zero-row result, or return None if there is nothing concrete to say.

    The returned text is fed straight back into the repair pass, so it is written as
    instruction rather than commentary.
    """
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s]
        if not statements:
            return None
        tree = statements[0]
    except Exception as e:  # noqa: BLE001 — a parse failure must not break the answer
        logger.debug("hybrid: empty_result_hint could not parse SQL (%s)", e)
        return None

    filters = _literal_filters(tree)
    if not filters:
        return None

    view_members = {m.name: m for m in catalog if m.view == view}
    lines: list[str] = []

    for column, literal in filters:
        member = view_members.get(column)
        if member is None:
            continue
        domain = value_domain(member.description)
        if not domain:
            continue

        if literal in domain:
            continue  # this filter is fine; some other predicate emptied the result

        folded = {v.casefold(): v for v in domain}
        actual = folded.get(literal.casefold())
        if actual:
            lines.append(
                f"'{literal}' is not a stored value — {column} stores '{actual}'. "
                f"String comparisons are case-sensitive; use the exact value."
            )
        else:
            listed = ", ".join(f"'{v}'" for v in domain[:MAX_LISTED_VALUES])
            more = "" if len(domain) <= MAX_LISTED_VALUES else f" (+{len(domain) - MAX_LISTED_VALUES} more)"
            lines.append(
                f"{column} has no value '{literal}'. Its valid values are: {listed}{more}."
            )

        segment = _segment_encoding(view_members, column, actual or literal)
        if segment:
            lines.append(
                f"The segment `{segment}` already encodes this filter — prefer "
                f"`WHERE {segment} = true` over a literal comparison."
            )

    if not lines:
        return None

    return ("The query ran successfully but returned 0 rows, which means a filter "
            "value is wrong.\n" + "\n".join(lines))
