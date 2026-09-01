"""Result-set comparison for benchmark scoring.

The retrieval benchmark already answers "did we find the right members?". This answers
the question that actually matters: "did we return the right NUMBERS?". A query that
runs cleanly and returns a wrong figure scores identically to a correct one under
`sql_ok` / `row_count > 0`, which is why execution accuracy needs its own comparator.

Four design points, each of which exists because the naive version gets it wrong:

  * COLUMN-MAJOR, hashed per column. Cube returns aggregates as
    `measure(view.total_preauth_count)` and `humanize()` rewrites them to
    `Total Preauth Count`, so comparing on column NAMES produces false negatives on
    correct answers. Comparing the md5 of each column's values sidesteps naming entirely.
  * MULTIPLE ACCEPTABLE ANSWERS per question. "Top providers" has several defensible
    shapes (with or without the count column, ties ordered either way); any match is a
    pass.
  * NORMALISATION before hashing. `Decimal('1.20')`, `1.2` and `"1.20"` are the same
    answer; `None` and `""` are the same absence; `True` and `1` are the same flag.
  * FOUR OUTCOMES, not a boolean. "ran but wrong" (WRONG) and "never ran" (FAILED /
    EXCEPTION) have completely different causes, and folding them together makes the
    accuracy number useless for deciding what to fix next.
"""
import hashlib
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

# Gold answers are stored column-major: {column_name: [value, value, ...]}.
GoldAnswer = dict[str, list[str]]

DEFAULT_SCALE = 2


class Outcome(str, Enum):
    RIGHT = "RIGHT"          # matched an accepted answer
    WRONG = "WRONG"          # ran and produced rows, none of the answers matched
    FAILED = "FAILED"        # no SQL produced, or the guard rejected it
    EXCEPTION = "EXCEPTION"  # the run raised


def normalize_cell(value: Any, scale: int = DEFAULT_SCALE) -> str:
    """One cell -> a canonical string.

    Numbers are rounded so 1.20 == 1.2 == "1.2000"; booleans collapse to 1/0 (Postgres
    and Cube disagree on how they come back); null and empty are the same thing.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"

    if isinstance(value, (int, float, Decimal)):
        try:
            quantized = Decimal(str(value)).quantize(Decimal(1).scaleb(-scale))
            return format(quantized.normalize(), "f")
        except (InvalidOperation, ValueError):
            return str(value).strip()

    text = str(value).strip()
    if not text:
        return ""

    # Numeric-looking strings normalise like numbers, so a gold file written by hand
    # ("29") matches a driver that returns Decimal('29.00').
    try:
        quantized = Decimal(text).quantize(Decimal(1).scaleb(-scale))
        return format(quantized.normalize(), "f")
    except (InvalidOperation, ValueError):
        return text


def to_column_major(columns: list[str], rows: list[dict]) -> GoldAnswer:
    """Row dicts -> {column: [normalized values]}, preserving row order."""
    return {c: [normalize_cell(r.get(c)) for r in rows] for c in columns}


def column_signature(values: list[str], ordered: bool = True) -> str:
    """Stable hash of one column's values.

    When order does not matter the values are sorted first, so "A,B" and "B,A" hash
    alike — correct for an unordered aggregate, wrong for a Top-N, which is why the
    caller chooses.
    """
    items = list(values) if ordered else sorted(values)
    joined = "\x1f".join(items)
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def _signatures(answer: GoldAnswer, ordered: bool) -> list[str]:
    return sorted(column_signature([normalize_cell(v) for v in vals], ordered)
                  for vals in answer.values())


def _matches(gold: GoldAnswer, actual: GoldAnswer, ordered: bool) -> bool:
    """One gold answer vs one actual result.

    Compared as multisets of column signatures, so column ORDER and column NAMES are
    both irrelevant — only the values matter. A gold answer with fewer columns than the
    result is a subset match: the benchmark author cared about the count, not about the
    identifying columns Cube also returned.
    """
    if not gold:
        return not any(actual.values())

    gold_sigs = _signatures(gold, ordered)
    actual_sigs = _signatures(actual, ordered)

    remaining = list(actual_sigs)
    for sig in gold_sigs:
        if sig not in remaining:
            return False
        remaining.remove(sig)
    return True


def compare(gold_answers: list[GoldAnswer], columns: list[str], rows: list[dict],
            ordered: bool = False) -> tuple[Outcome, dict]:
    """Score one result set against every acceptable answer. Any match wins.

    Returns (outcome, detail) where detail explains a miss well enough to debug it
    without re-running the question.
    """
    actual = to_column_major(columns, rows)

    if not gold_answers:
        return Outcome.FAILED, {"why": "no gold answer recorded for this question"}

    for i, gold in enumerate(gold_answers):
        if _matches(gold, actual, ordered):
            return Outcome.RIGHT, {"matched_answer": i, "ordered": ordered}

    return Outcome.WRONG, {
        "ordered": ordered,
        "actual_columns": list(actual),
        "actual_row_count": len(rows),
        "actual": {c: v[:5] for c, v in actual.items()},
        "expected_any_of": [{c: v[:5] for c, v in g.items()} for g in gold_answers],
    }


def score(results: list[tuple[Outcome, dict]]) -> dict:
    """Aggregate outcomes into the two headline rates.

    `accuracy` is what fraction of questions were answered correctly; `exec_rate` is
    what fraction produced a runnable query at all. Tracking both separates a
    generation problem from a correctness problem.
    """
    counts = {o: 0 for o in Outcome}
    for outcome, _ in results:
        counts[outcome] += 1

    total = len(results) or 1
    ran = counts[Outcome.RIGHT] + counts[Outcome.WRONG]
    return {
        "total": len(results),
        "right": counts[Outcome.RIGHT],
        "wrong": counts[Outcome.WRONG],
        "failed": counts[Outcome.FAILED],
        "exception": counts[Outcome.EXCEPTION],
        "accuracy": counts[Outcome.RIGHT] / total,
        "exec_rate": ran / total,
    }
