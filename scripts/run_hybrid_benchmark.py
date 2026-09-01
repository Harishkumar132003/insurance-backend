#!/usr/bin/env python3
"""Score the hybrid pipeline against the 45 existing benchmark questions.

    venv/bin/python scripts/run_hybrid_benchmark.py --retrieval-only   # no SQL, cheaper
    venv/bin/python scripts/run_hybrid_benchmark.py --execute
    venv/bin/python scripts/run_hybrid_benchmark.py --limit 5 --json out.json

Execution ACCURACY (did we return the right numbers?) needs gold result sets, which the
markdown files do not carry — they hold expected members and views only. Bootstrap them
once, review by hand, then score against them:

    ... --execute --record-gold gold.json     # capture current results as CANDIDATES
    ... --execute --gold gold.json            # score against the reviewed file

The recorded file is a starting point, not a baseline: recording a wrong answer and then
scoring against it measures nothing. Read it before you trust it.

Reads the two markdown files in the repo root. They have DIFFERENT column counts —
the 20-question file is `# | Query | Expected | View` and the 25-question file inserts
a Difficulty column — so parsing is header-driven, not positional.

The headline number is `recall@30 merged` vs `recall@20 vector`: if fusing the BM25 arm
doesn't lift recall, the keyword half isn't earning its place.

A caveat worth remembering when reading the output: the gold labels are imperfect. One
expected member (`preauth_status_transition_path`) exists in no view at all, and a few
(member, view) pairs are self-inconsistent — the labelled view doesn't contain the
labelled member. Those are reported separately rather than silently counted as failures.
"""
import argparse
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.hybrid.compare import (  # noqa: E402
    Outcome,
    compare,
    score as score_outcomes,
    to_column_major,
)
from app.services.hybrid.cube_meta import get_catalog  # noqa: E402
from app.services.hybrid.pipeline import run_pipeline  # noqa: E402
from app.services.hybrid.retrieval import selected_qnames  # noqa: E402

REPO = "/home/wizzgeeks/workspace/oasys"
FILES = [
    os.path.join(REPO, "ai_agent_test_queries_benchmark.md"),
    os.path.join(REPO, "preauth_claims_25_questions_benchmark.md"),
]

_BACKTICK = re.compile(r"`([A-Za-z0-9_]+)`")
_SEPARATOR = re.compile(r"^[\s:|-]+$")


def _clean(cell: str) -> str:
    return cell.replace("**", "").strip()


def parse_file(path: str) -> list[dict]:
    """Header-driven markdown table parser. Each `| # | ... |` header row resets the
    column map, so multiple tables per file (and differing column counts) both work."""
    cases, header = [], None
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(_SEPARATOR.match(c) or not c for c in cells):
                continue
            low = [_clean(c).lower() for c in cells]
            if any("natural language" in c for c in low):
                header = low
                continue
            if not header or len(cells) != len(header):
                continue

            row = dict(zip(header, cells))
            qcol = next((k for k in header if "natural language" in k), None)
            ecol = next((k for k in header if "expected" in k), None)
            vcol = next((k for k in header if "target view" in k), None)
            if not (qcol and ecol and vcol):
                continue

            question = _clean(row[qcol]).strip('"').strip()
            if not question:
                continue
            cases.append({
                "source": os.path.basename(path),
                "id": _clean(row.get("#", "")),
                "question": question,
                "expected_members": _BACKTICK.findall(row[ecol]),
                "expected_view": _clean(row[vcol]).strip("`"),
            })
    return cases


def _names(qnames) -> set[str]:
    """Compare on the short field name — the same member exists in several views."""
    return {q.split(".", 1)[-1] for q in qnames if q}


def recall(expected: set[str], got: set[str]) -> float | None:
    return (len(expected & got) / len(expected)) if expected else None


async def score_case(case: dict, all_member_names: set[str], execute: bool,
                     hospital_id: str | None, gold: dict | None = None) -> dict:
    stop = "answer" if execute else "retrieval"
    res = await run_pipeline(case["question"], hospital_id=hospital_id,
                             stop_after=stop, include_trace=True)
    t = res.trace

    # A gold member that exists in NO view can never be retrieved — exclude it from the
    # denominator instead of permanently capping recall below 1.0.
    expected = set(case["expected_members"])
    unattainable = sorted(expected - all_member_names)
    attainable = expected & all_member_names

    vec = _names(h.qname for h in (t.vector_hits if t else []))
    kw = _names(h.qname for h in (t.keyword_hits if t else []))
    merged = _names(h.qname for h in (t.merged if t else []))
    reranked = _names(h.qname for h in (t.reranked if t else []))
    selected = _names(selected_qnames(t.selected)) if (t and t.selected) else set()

    phrases = [p.phrase for p in t.concepts.phrases] if (t and t.concepts) else []
    entities = [e.value for e in t.concepts.entities] if (t and t.concepts) else []
    leak = [p for p in phrases for e in entities if e.lower() in p.lower()]

    return {
        "id": case["id"], "source": case["source"], "question": case["question"],
        "expected_view": case["expected_view"], "derived_view": res.view,
        "view_match": res.view == case["expected_view"],
        "view_attainable": bool(t and not (t.view_derivation or {}).get("fallback")),
        "expected_members": sorted(expected),
        "unattainable": unattainable,
        "phrase_count": len(phrases), "phrases": phrases,
        "entities": entities, "entity_leak": leak,
        "recall_vector": recall(attainable, vec),
        "recall_keyword": recall(attainable, kw),
        "recall_merged": recall(attainable, merged),
        "recall_reranked": recall(attainable, reranked),
        "recall_selected": recall(attainable, selected),
        "missed": sorted(attainable - merged),
        "sql": res.sql, "sql_ok": bool(res.sql and res.row_count is not None),
        "row_count": res.row_count, "answer": res.answer, "notes": res.notes,
        "ms": (t.timings_ms or {}).get("total") if t else None,
        # Attribution for the two new accuracy mechanisms, so a moved number can be
        # traced to the change that moved it.
        "identifier_probe": (t.identifier_probe if t else []) or [],
        "empty_repair": any("empty_result_hint" in a
                            for a in (t.sql_attempts if t else [])),
        "attempts": len(t.sql_attempts) if t else 0,
        # Column-major result, in the shape --record-gold writes out.
        "result": to_column_major(res.columns, res.rows) if execute else None,
        **_grade(case, res, execute, gold),
    }


def _grade(case: dict, res, execute: bool, gold: dict | None) -> dict:
    """Compare the result set against the accepted answers for this question."""
    if not execute or gold is None:
        return {}

    entry = gold.get(str(case["id"])) or {}
    answers = entry.get("answers") or []
    ordered = bool(entry.get("ordered", False))

    if not res.sql:
        return {"outcome": Outcome.FAILED.value,
                "outcome_detail": {"why": res.notes or "no SQL generated"}}

    outcome, detail = compare(answers, res.columns, res.rows, ordered=ordered)
    return {"outcome": outcome.value, "outcome_detail": detail}


def _mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def _pct(v) -> str:
    return f"{100 * v:5.1f}%" if v is not None else "    - "


def report_accuracy(results: list[dict]) -> None:
    """Execution accuracy — the number `sql_ok` cannot give you.

    `right/wrong` and `failed/exception` answer different questions: the first is a
    correctness problem, the second a generation problem. Reporting one number hides
    which one you have.
    """
    graded = [r for r in results if r.get("outcome")]
    if not graded:
        return

    pairs = [(Outcome(r["outcome"]), r.get("outcome_detail") or {}) for r in graded]
    st = score_outcomes(pairs)

    print(f"\nEXECUTION ACCURACY  (graded={st['total']}/{len(results)})")
    print(f"  RIGHT / WRONG / FAILED / EXCEPTION   "
          f"{st['right']} / {st['wrong']} / {st['failed']} / {st['exception']}")
    print(f"  accuracy  (right / total)            {_pct(st['accuracy'])}")
    print(f"  exec rate ((right+wrong) / total)    {_pct(st['exec_rate'])}")

    ungraded = [r["id"] for r in results if not r.get("outcome")]
    if ungraded:
        print(f"  no gold answer, not counted          {len(ungraded)}  {ungraded[:10]}")

    wrong = [r for r in graded if r["outcome"] == Outcome.WRONG.value]
    if wrong:
        print("\n  WRONG ANSWERS")
        for r in wrong[:10]:
            d = r.get("outcome_detail") or {}
            print(f"    {r['id']}: got {d.get('actual')}")
            print(f"         expected any of {d.get('expected_any_of')}")
            print(f"         {r['question'][:88]}")


def report_mechanisms(results: list[dict]) -> None:
    """How often the two new accuracy mechanisms actually fired."""
    probed = [r for r in results if r.get("identifier_probe")]
    resolved = [r for r in probed
                if any(p.get("resolved_field") for p in r["identifier_probe"])]
    corrected = [r for r in probed
                 for p in r["identifier_probe"]
                 if p.get("resolved_field")
                 and p.get("claimed_kind") not in (None, "other")
                 and p.get("resolved_field") != _field_for_kind(p.get("claimed_kind"))]
    repaired = [r for r in results if r.get("empty_repair")]

    print("\nACCURACY MECHANISMS")
    print(f"  identifier probe ran                 {len(probed)}")
    print(f"    resolved to one field              {len(resolved)}")
    print(f"    CORRECTED a wrong kind             {len(corrected)}"
          + (f"  {[r['id'] for r in corrected][:10]}" if corrected else ""))
    print(f"  empty-result repair fired            {len(repaired)}"
          + (f"  {[r['id'] for r in repaired][:10]}" if repaired else ""))


def _field_for_kind(kind: str | None) -> str | None:
    """The field a claimed kind would have pointed at, for corrected-guess counting."""
    from app.services.hybrid.identifiers import PROBE_FIELDS

    return next((f for f, k in PROBE_FIELDS if k == kind), None)


def write_gold(results: list[dict], path: str) -> None:
    """Record the current run as CANDIDATE gold answers.

    Deliberately not called a baseline. These are whatever the pipeline said today,
    including its mistakes; the file has to be read and corrected before scoring
    against it means anything. Questions that produced no SQL are written with an
    empty answer list so they show up as FAILED rather than silently passing.
    """
    gold = {}
    for r in results:
        answers = [r["result"]] if r.get("result") is not None and r.get("sql") else []
        gold[str(r["id"])] = {
            "question": r["question"],
            "ordered": False,
            "_review": "UNREVIEWED - captured from a pipeline run, verify before use",
            "answers": answers,
        }
    with open(path, "w") as fh:
        json.dump(gold, fh, indent=2, default=str)
    print(f"\nWrote {len(gold)} CANDIDATE gold answers to {path}")
    print("These are unverified pipeline output. Review them before scoring against them.")


def report(results: list[dict], execute: bool) -> None:
    print("\n" + "=" * 108)
    print(f"{'id':6s} {'view: expected -> derived':46s} {'ok':3s} {'vec':>6s} {'kw':>6s} "
          f"{'merged':>7s} {'rerank':>7s} {'sel':>6s}")
    print("-" * 108)
    for r in results:
        arrow = f"{r['expected_view']} -> {r['derived_view']}"
        print(f"{r['id']:6s} {arrow:46s} {'Y' if r['view_match'] else 'n':3s} "
              f"{_pct(r['recall_vector'])} {_pct(r['recall_keyword'])} "
              f"{_pct(r['recall_merged'])} {_pct(r['recall_reranked'])} {_pct(r['recall_selected'])}")

    n = len(results)
    print("=" * 108)
    print(f"\nRETRIEVAL  (n={n})")
    print(f"  view match          {_pct(sum(r['view_match'] for r in results) / n)}")
    print(f"  recall@20 vector    {_pct(_mean(r['recall_vector'] for r in results))}")
    print(f"  recall@20 keyword   {_pct(_mean(r['recall_keyword'] for r in results))}")
    print(f"  recall@30 merged    {_pct(_mean(r['recall_merged'] for r in results))}   <- hybrid payoff")
    print(f"  recall@8  reranked  {_pct(_mean(r['recall_reranked'] for r in results))}")
    print(f"  recall    selected  {_pct(_mean(r['recall_selected'] for r in results))}")

    gain = (_mean(r["recall_merged"] for r in results) or 0) - (_mean(r["recall_vector"] for r in results) or 0)
    kw_only = [r for r in results
               if (r["recall_keyword"] or 0) > (r["recall_vector"] or 0)]
    print(f"\n  merged - vector     {gain * 100:+5.1f} points")
    print(f"  questions where keyword beat vector: {len(kw_only)}"
          + (f"  {[r['id'] for r in kw_only]}" if kw_only else ""))

    print("\nCONCEPT EXTRACTION")
    print(f"  avg phrases/question {_mean(float(r['phrase_count']) for r in results):.2f}")
    leaks = [r for r in results if r["entity_leak"]]
    print(f"  entity leaks         {len(leaks)} (should be 0)"
          + (f"  {[r['id'] for r in leaks]}" if leaks else ""))

    if execute:
        ok = sum(1 for r in results if r["sql_ok"])
        rows = sum(1 for r in results if (r["row_count"] or 0) > 0)
        print("\nEXECUTION")
        print(f"  sql ok               {ok}/{n}  ({100 * ok / n:.0f}%)")
        print(f"  returned rows        {rows}/{n}")
        print(f"  median latency       {sorted(r['ms'] or 0 for r in results)[n // 2]} ms")

    bad_labels = [r for r in results if r["unattainable"]]
    if bad_labels:
        print("\nGOLD-LABEL DEFECTS (excluded from recall denominators)")
        for r in bad_labels:
            print(f"  {r['id']}: {r['unattainable']} exists in no view")

    if execute:
        report_accuracy(results)
        report_mechanisms(results)

    worst = sorted((r for r in results if r["recall_merged"] is not None),
                   key=lambda r: r["recall_merged"])[:5]
    print("\nWORST RETRIEVAL")
    for r in worst:
        print(f"  {r['id']} {_pct(r['recall_merged'])} missed={r['missed']}")
        print(f"       {r['question'][:92]}")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--execute", action="store_true", help="generate and run SQL too")
    ap.add_argument("--retrieval-only", action="store_true", default=False)
    ap.add_argument("--hospital-id", default=None)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--json", dest="json_path")
    ap.add_argument("--gold", dest="gold_path",
                    help="JSON of accepted result sets; enables execution accuracy")
    ap.add_argument("--record-gold", dest="record_gold_path",
                    help="write this run's results as CANDIDATE gold answers")
    args = ap.parse_args()

    execute = args.execute and not args.retrieval_only

    cases = []
    for path in FILES:
        if os.path.exists(path):
            cases.extend(parse_file(path))
        else:
            print(f"missing benchmark file: {path}")
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    if args.limit:
        cases = cases[:args.limit]
    print(f"Parsed {len(cases)} benchmark questions from {len(FILES)} files.")
    if not cases:
        return 1

    gold = None
    if args.gold_path:
        if not os.path.exists(args.gold_path):
            print(f"missing gold file: {args.gold_path}")
            return 1
        with open(args.gold_path) as fh:
            gold = json.load(fh)
        print(f"Loaded {len(gold)} gold answers from {args.gold_path}.")
        unreviewed = [k for k, v in gold.items() if v.get("_review")]
        if unreviewed:
            print(f"  WARNING: {len(unreviewed)} entries are still marked UNREVIEWED — "
                  f"scoring against unverified answers measures nothing.")
    if (args.gold_path or args.record_gold_path) and not execute:
        print("--gold/--record-gold need --execute (there are no results to compare).")
        return 1

    catalog = await get_catalog()
    all_names = {m.name for m in catalog}

    sem = asyncio.Semaphore(args.concurrency)

    async def guarded(case):
        async with sem:
            try:
                return await score_case(case, all_names, execute, args.hospital_id, gold)
            except Exception as e:  # noqa: BLE001 — one bad question must not kill the run
                print(f"  [{case['id']}] ERROR {e}")
                return {"id": case["id"], "source": case["source"],
                        "question": case["question"],
                        "expected_view": case["expected_view"], "derived_view": None,
                        "view_match": False, "expected_members": case["expected_members"],
                        "unattainable": [], "phrase_count": 0, "phrases": [],
                        "entities": [], "entity_leak": [],
                        "recall_vector": None, "recall_keyword": None,
                        "recall_merged": None, "recall_reranked": None,
                        "recall_selected": None, "missed": [], "sql": None,
                        "sql_ok": False, "row_count": None, "answer": "",
                        "notes": str(e), "ms": None,
                        "identifier_probe": [], "empty_repair": False,
                        "attempts": 0, "result": None,
                        # A question that raised is EXCEPTION, never WRONG — folding
                        # the two together hides infrastructure failures as accuracy.
                        **({"outcome": Outcome.EXCEPTION.value,
                            "outcome_detail": {"why": str(e)}} if execute and gold else {})}

    results = await asyncio.gather(*(guarded(c) for c in cases))
    results = list(results)
    report(results, execute)

    if args.record_gold_path:
        write_gold(results, args.record_gold_path)

    if args.json_path:
        with open(args.json_path, "w") as fh:
            json.dump(results, fh, indent=2, default=str)
        print(f"\nWrote {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
