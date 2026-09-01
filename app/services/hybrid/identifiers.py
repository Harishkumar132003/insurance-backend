"""Resolve an ambiguous identifier by asking the data, not the model.

The concept extractor labels every literal it lifts out of a question with an
`EntityKind` — but for a bare number that label is a guess, and the guess cannot be
made reliable by better prompting, because the formats genuinely overlap. Measured
against live data:

    hospitalization.uhid                      260029370955, 98624635, HSP-2026-000123
    hospitalization.claim_number              2321321, 556222122371761, CL260029370955
    patient_personal_detail.policy_number     631233521351, POL52435

Three different fields hold 12-digit numeric values, and one claim number contains a
UHID verbatim. No length, charset or prefix rule separates them, so reasoning harder
cannot help: only looking can.

One SELECT settles it. Every candidate field is exposed on `master_hospital_360`, and
at current volumes the probe is free. A wrong guess otherwise costs a filter on the
wrong column, zero rows, and a confident "no matching records were found".
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field

from app.schemas.hybrid import Entity
from app.services.hybrid.common import log

logger = logging.getLogger("app.hybrid")

# Pinned to the widest view rather than the derived one: `policy_number` is absent from
# preauth_tat_workflow, and resolution has to happen BEFORE the view is derived anyway.
PROBE_VIEW = "master_hospital_360"

# (view field, EntityKind it implies). Order is the tie-break shown to the model.
PROBE_FIELDS: tuple[tuple[str, str], ...] = (
    ("uhid", "uhid"),
    ("claim_number", "claim"),
    ("policy_number", "policy"),
    ("settlement_claim_number", "claim"),
    ("settlement_number", "settlement"),
)

# Kinds that name a person or organisation. Those are matched with ILIKE against long
# legal names, not looked up by equality, so probing them would be meaningless.
_NAME_KINDS = frozenset({"provider", "hospital", "corporate", "patient"})

MIN_LEN = 4
MAX_LEN = 40
MAX_PROBE_VALUES = 3       # a question rarely contains more than one identifier
PROBE_ROW_LIMIT = 5

_HAS_DIGIT = re.compile(r"\d")
_HAS_SPACE = re.compile(r"\s")


@dataclass(frozen=True)
class Resolution:
    """What the data says about one literal value."""
    value: str
    claimed_kind: str = "other"                 # what the extractor guessed
    matched: tuple[str, ...] = ()               # fields that actually contain it
    probed: tuple[str, ...] = ()                # fields that were checked
    error: str | None = None

    @property
    def resolved_field(self) -> str | None:
        """The single field this value belongs to, or None if it is still ambiguous."""
        return self.matched[0] if len(self.matched) == 1 else None

    @property
    def resolved_kind(self) -> str | None:
        f = self.resolved_field
        if not f:
            return None
        return dict(PROBE_FIELDS).get(f)

    def to_dict(self) -> dict:
        return {"value": self.value, "claimed_kind": self.claimed_kind,
                "matched": list(self.matched), "probed": list(self.probed),
                "resolved_field": self.resolved_field, "error": self.error}


def looks_like_identifier(entity: Entity) -> bool:
    """Should this literal be probed?

    Shape decides only WHETHER to look, never WHAT the value is — a false positive
    costs one cheap query, a false negative costs a wrong answer. So the test is
    deliberately loose: no whitespace, plausible length, at least one digit, and not
    already labelled as a person or organisation name.
    """
    value = (entity.value or "").strip()
    if not value or _HAS_SPACE.search(value):
        return False
    if not (MIN_LEN <= len(value) <= MAX_LEN):
        return False
    if not _HAS_DIGIT.search(value):
        return False
    return entity.kind not in _NAME_KINDS


def _available_fields(catalog: list) -> tuple[str, ...]:
    """PROBE_FIELDS that the live Cube model actually exposes on the probe view.

    A model change should narrow the probe, never break it.
    """
    present = {m.name for m in catalog if m.view == PROBE_VIEW}
    return tuple(f for f, _ in PROBE_FIELDS if f in present)


def build_probe_sql(fields: tuple[str, ...]) -> str:
    """The probe statement. Issued by us, so it never passes through guard_sql — that
    guard exists to police model-written SQL, and this is not that.

    The hospital_id predicate is not optional: the Cube path has no row-level security,
    tenant scoping is applied by rewriting model SQL, and this query bypasses that
    rewrite. Without the predicate the probe would read across tenants.
    """
    selected = ", ".join(fields)
    ors = " OR ".join(f"{f} = %s" for f in fields)
    groups = ", ".join(str(i + 1) for i in range(len(fields)))
    return (f"SELECT {selected} FROM {PROBE_VIEW} "
            f"WHERE hospital_id = %s AND ({ors}) "
            f"GROUP BY {groups} LIMIT {PROBE_ROW_LIMIT}")


async def _probe_one(value: str, claimed_kind: str, fields: tuple[str, ...],
                     hospital_id: str) -> Resolution:
    from app.services.hybrid.execute import run_cube_sql

    sql = build_probe_sql(fields)
    params = (hospital_id, *([value] * len(fields)))
    try:
        _, rows = await run_cube_sql(sql, params)
    except Exception as e:  # noqa: BLE001 — never let a probe take the answer down
        log("identify", "probe FAILED for %r (%s)", value, e)
        return Resolution(value=value, claimed_kind=claimed_kind,
                          probed=fields, error=str(e))

    matched = tuple(f for f in fields
                    if any(str(r.get(f) or "") == value for r in rows))
    log("identify", "%r matched %s (claimed %s)", value, list(matched) or "nothing",
        claimed_kind)
    return Resolution(value=value, claimed_kind=claimed_kind,
                      matched=matched, probed=fields)


async def resolve(entities: list[Entity], hospital_id: str | None,
                  catalog: list) -> list[Resolution]:
    """Probe every identifier-shaped literal in the question. Never raises."""
    if not hospital_id:
        # Refusing to probe unscoped is the whole point — see build_probe_sql.
        return []

    candidates: list[Entity] = []
    seen: set[str] = set()
    for e in entities:
        value = (e.value or "").strip()
        if value in seen or not looks_like_identifier(e):
            continue
        seen.add(value)
        candidates.append(e)
        if len(candidates) >= MAX_PROBE_VALUES:
            break

    if not candidates:
        return []

    fields = _available_fields(catalog)
    if not fields:
        log("identify", "no probe fields on %s — skipping", PROBE_VIEW)
        return []

    return list(await asyncio.gather(*(
        _probe_one(e.value.strip(), e.kind, fields, hospital_id) for e in candidates
    )))


def resolution_hint(resolutions: list[Resolution]) -> str:
    """Render resolutions for the SQL prompt.

    Written as fact rather than suggestion — this is the one thing in the prompt that
    was verified against the database, and it should outrank the model's own guess.
    """
    lines: list[str] = []
    for r in resolutions:
        if r.error:
            continue
        if len(r.matched) == 1:
            f = r.matched[0]
            lines.append(f"  {r.value} is a {f} (verified against the data). "
                         f"Filter with {f} = '{r.value}'.")
        elif len(r.matched) > 1:
            names = " and ".join(r.matched)
            lines.append(f"  {r.value} exists in both {names} — filter on whichever "
                         f"the question means.")
        else:
            checked = ", ".join(r.probed)
            lines.append(f"  {r.value} was NOT found in any of: {checked}. Do not "
                         f"invent a different filter for it; if the question depends "
                         f"on this value, the honest answer is that no such record "
                         f"exists.")
    if not lines:
        return ""
    return "IDENTIFIERS resolved against the data (trust these over the labels above):\n" + "\n".join(lines)
