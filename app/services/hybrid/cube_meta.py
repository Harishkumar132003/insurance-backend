"""Cube /meta catalog for the hybrid pipeline.

One `Member` per (view, field) exposed by Cube's semantic layer. This is the single
source of truth the whole v2 pipeline retrieves over — the vector index, the BM25
index and every LLM prompt are all built from it, so they can never disagree about
what exists.

Three things this does that the production pipeline does not:

  * stores the QUERYABLE name (`master_hospital_360.total_claim_count`) rather than
    the bare field name, so a retrieved member is directly usable in SQL;
  * patches the 17 members Cube exposes with no description at all (all of
    claim_case_emails plus patient_name / policy_number) — undescribed members are
    close to invisible to both dense and lexical retrieval;
  * resolves each member's SOURCE CUBE, including for segments (whose `aliasMember`
    is null in /meta), which is what the fan-out guard needs.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

from app.core.config import settings

logger = logging.getLogger("app.hybrid")

# Seconds to cache /meta. A Cube model change is picked up automatically within this
# window; the Qdrant collection still needs an explicit reindex (see /ai2/health).
CUBE_META_TTL = 300

# Views the pipeline is allowed to query. Cube exposes 8; these are the 5 the product
# uses and the 5 the benchmark files target. Add "revenue_lifecycle",
# "claims_operations", "preauth_operations" here to widen coverage.
ALLOWED_VIEWS = [
    "master_hospital_360",
    "desk_operations_queue",
    "preauth_tat_workflow",
    "claims_settlement_recon",
    "case_communications",
]

# Children of `hospitalization` joined one_to_many. Mixing measures from two of these
# branches in ONE query is safe: Cube resolves it as per-fact subqueries joined on the
# shared dimensions, and the values match separately-queried ones exactly (verified in
# tests/test_fanout.py). These names are still needed to rank views in `derive_view` —
# a view carrying branches the question does not need is a wider join than necessary.
FANOUT_CUBES = {
    "preauth_status_tracking",
    "claim_status_tracking",
    "settlement_item",
    "claim_case_emails",
    "settlement_batch",
}

# Cube returns description: None for these. Keyed by aliasMember (source cube.field) so
# one entry covers every view that includes the field. Fixing the YAML at source is the
# real fix; this keeps retrieval working until then.
DESC_OVERRIDES: dict[str, str] = {
    # --- claim_case_emails: 15 of the 17 offenders; case_communications is 65% undescribed
    "claim_case_emails.count":
        "Number of correspondence emails on the case. Use for 'how many emails', "
        "'email count', 'correspondence volume'. NOT a count of cases, pre-auths or claims.",
    "claim_case_emails.subject": "Subject line of the insurer/TPA correspondence email.",
    "claim_case_emails.from_email": "Sender email address of the correspondence.",
    "claim_case_emails.to_email": "Recipient email address of the correspondence.",
    "claim_case_emails.email_type":
        "Category of the email, e.g. query, denial, approval, document request.",
    "claim_case_emails.direction":
        "Whether the email was INBOUND (received from the insurer/TPA) or OUTBOUND (sent by the hospital).",
    "claim_case_emails.body": "Full plain-text body of the correspondence email.",
    "claim_case_emails.ai_summary":
        "AI-generated summary of what the insurer's email said. Use for 'email summary', "
        "'what did the insurer say', 'correspondence summary'.",
    "claim_case_emails.ai_denial_reason":
        "AI-extracted reason the insurer gave for denying or rejecting the case.",
    "claim_case_emails.ai_query_details":
        "AI-extracted details of the query / ADR / NMI the insurer raised — what additional "
        "information was asked for.",
    "claim_case_emails.ai_documents_requested":
        "Whether the insurer's email requested supporting documents (boolean).",
    "claim_case_emails.ai_documents_list":
        "AI-extracted list of the supporting documents the insurer asked for.",
    "claim_case_emails.is_read": "Whether the email has been read by hospital staff.",
    "claim_case_emails.email_date":
        "Date the correspondence email was sent or received. Use for email time filters and trends.",
    "claim_case_emails.created_at": "When the email record was created in the system.",
    # --- patient_personal_detail: the two highest-value fixes, very common query terms
    "patient_personal_detail.patient_name":
        "Patient full name. Use to look up or filter a case by the patient's name.",
    "patient_personal_detail.policy_number":
        "Insurance policy number on the patient's policy. Use to look up a case by policy number.",
}

# Members that HAVE a description but omit the word users actually search by. Appended,
# not replaced, so the model's own wording is preserved. Without this, "bank UTR number"
# lexically matches the batch AMOUNT measures (whose descriptions say "UTR") instead of
# settlement_number, which is the field that actually holds it.
DESC_AUGMENT: dict[str, str] = {
    "settlement_batch.settlement_number":
        "Also called the UTR, bank UTR, transaction reference, or remittance number.",
    "settlement_batch.batch_settlement_date":
        "The UTR / remittance payment date.",
    "settlement_item.settlement_disallowance_reason":
        "The short-pay reason — why the insurer deducted or disallowed part of the claim.",
    "preauth_status_tracking.preauth_queries_received_count":
        "Counts ADR (Additional Documents Required) and NMI (Need More Information) queries.",
    "claim_status_tracking.claim_queries_received_count":
        "Counts ADR (Additional Documents Required) and NMI (Need More Information) queries.",
    "preauth_status_tracking.preauth_is_query_raised_event":
        "Marks an ADR / NMI query event.",
    "claim_status_tracking.claim_is_query_raised_event":
        "Marks an ADR / NMI query event.",
}


@dataclass
class Member:
    """One queryable field of one Cube view."""
    qname: str          # "master_hospital_360.total_claim_count" — what SQL uses
    view: str           # "master_hospital_360"
    name: str           # "total_claim_count" — unprefixed
    kind: str           # measure | dimension | segment
    dtype: str          # number | string | time | boolean | ""
    agg: str            # sum | count | avg | ... (measures only)
    title: str          # shortTitle
    description: str    # enriched via DESC_OVERRIDES
    cube: str           # source cube, e.g. "pre_auth" ("" if unresolvable)

    def render(self) -> str:
        """One menu line for an LLM prompt."""
        tag = self.kind.upper() if self.kind == "measure" else f"{self.kind}/{self.dtype or '?'}"
        desc = f" — {self.description}" if self.description else ""
        return f"  {self.qname} [{tag}]{desc}"


@dataclass
class _Cache:
    meta: dict | None = None
    catalog: list[Member] = field(default_factory=list)
    fetched_at: float = 0.0


_cache = _Cache()
_lock = asyncio.Lock()


def _auth_headers() -> dict:
    """Cube in dev mode needs no token. When CUBE_API_SECRET is set, sign an empty
    payload — Cube accepts the raw JWT in the Authorization header (no Bearer prefix)."""
    if not settings.CUBE_API_SECRET:
        return {}
    try:
        import jwt  # PyJWT, already installed
        token = jwt.encode({}, settings.CUBE_API_SECRET, algorithm="HS256")
        return {"Authorization": token}
    except Exception as e:  # noqa: BLE001 — a bad secret must not take /meta down
        logger.warning("hybrid: could not sign Cube JWT (%s), falling back to no auth", e)
        return {}


async def fetch_meta(force: bool = False) -> dict:
    """GET /cubejs-api/v1/meta, cached for CUBE_META_TTL. Retries once without the
    Authorization header, since dev-mode Cube rejects an unexpected token."""
    if not force and _cache.meta and (time.time() - _cache.fetched_at) < CUBE_META_TTL:
        return _cache.meta

    url = f"{settings.CUBE_API_URL.rstrip('/')}/cubejs-api/v1/meta"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=_auth_headers())
        if r.status_code in (401, 403) and _auth_headers():
            r = await client.get(url)
        r.raise_for_status()
        meta = r.json()

    if "error" in meta:
        raise RuntimeError(f"Cube /meta returned an error (schema compile failure?): {meta['error']}")

    _cache.meta = meta
    _cache.fetched_at = time.time()
    _cache.catalog = []  # invalidate derived catalog
    return meta


def _segment_cube_map(meta: dict) -> dict[str, str]:
    """View segments carry `aliasMember: null`, so the source cube has to come from the
    RAW cubes, which do declare their segments. Returns {segment_field_name: cube}."""
    out: dict[str, str] = {}
    for c in meta.get("cubes", []):
        if c.get("type") == "view":
            continue
        cube = c["name"]
        for s in c.get("segments", []):
            fname = s["name"].split(".", 1)[-1]
            out.setdefault(fname, cube)
    return out


def _build_catalog(meta: dict) -> list[Member]:
    seg_cubes = _segment_cube_map(meta)
    members: list[Member] = []

    for c in meta.get("cubes", []):
        if c.get("type") != "view" or c["name"] not in ALLOWED_VIEWS:
            continue
        view = c["name"]

        for kind, key in (("measure", "measures"), ("dimension", "dimensions"), ("segment", "segments")):
            for m in c.get(key, []):
                qname = m["name"]                       # already view-prefixed
                name = qname.split(".", 1)[-1]
                alias = m.get("aliasMember") or ""
                if alias:
                    cube = alias.split(".", 1)[0]
                elif kind == "segment":
                    cube = seg_cubes.get(name, "")
                else:
                    cube = ""

                key = alias or (f"{cube}.{name}" if cube else "")
                desc = (m.get("description") or "").strip()
                if not desc and key:
                    desc = DESC_OVERRIDES.get(key, "")
                extra = DESC_AUGMENT.get(key, "") if key else ""
                if extra and extra not in desc:
                    desc = f"{desc} {extra}".strip()

                members.append(Member(
                    qname=qname,
                    view=view,
                    name=name,
                    kind=kind,
                    dtype=(m.get("type") or "" if kind != "segment" else "boolean"),
                    agg=(m.get("aggType") or "" if kind == "measure" else ""),
                    title=(m.get("shortTitle") or m.get("title") or "").strip(),
                    description=desc,
                    cube=cube,
                ))
    return members


async def get_catalog(force: bool = False) -> list[Member]:
    """The member catalog, cached alongside /meta."""
    async with _lock:
        if not force and _cache.catalog and (time.time() - _cache.fetched_at) < CUBE_META_TTL:
            return _cache.catalog
        meta = await fetch_meta(force=force)
        _cache.catalog = _build_catalog(meta)
        missing = [m.qname for m in _cache.catalog if not m.description]
        logger.info("hybrid: catalog built — %d members across %d views%s",
                    len(_cache.catalog), len(ALLOWED_VIEWS),
                    f", {len(missing)} still undescribed" if missing else "")
        if missing:
            logger.warning("hybrid: undescribed members (weak retrieval): %s", missing[:20])
        return _cache.catalog


def by_qname(catalog: list[Member]) -> dict[str, Member]:
    return {m.qname: m for m in catalog}


def members_by_view(catalog: list[Member]) -> dict[str, list[Member]]:
    out: dict[str, list[Member]] = {}
    for m in catalog:
        out.setdefault(m.view, []).append(m)
    return out


def fanout_branch(m: Member) -> str | None:
    """The one_to_many branch this member hangs off, or None if it is safe to combine."""
    return m.cube if m.cube in FANOUT_CUBES else None


def derive_view(qnames: list[str], catalog: list[Member]) -> tuple[str, dict]:
    """Pick the target view FROM the selected members, instead of committing to a view
    before retrieval (which the production pipeline does, unrecoverably).

    Chooses the NARROWEST view that exposes every selected field — fewer joins means
    less fan-out risk. Returns (view, trace) where trace explains the choice.
    """
    fields = {q.split(".", 1)[-1] for q in qnames if q}
    per_view = members_by_view(catalog)
    sizes = {v: len(ms) for v, ms in per_view.items()}
    names_per_view = {v: {m.name for m in ms} for v, ms in per_view.items()}

    candidates = [v for v in ALLOWED_VIEWS
                  if v in names_per_view and fields <= names_per_view[v]]

    if candidates:
        # Which one_to_many branches does this question actually need?
        # Matched on the SHORT field name, like `fields` above — callers pass either
        # bare or view-qualified names and both must behave identically.
        needed = {b for b in (fanout_branch(m) for m in catalog
                              if m.name in fields) if b}
        # Branches each view drags in whether or not they were asked for.
        branches_of = {
            v: {b for b in (fanout_branch(m) for m in ms) if b}
            for v, ms in per_view.items()
        }
        # Prefer the view carrying the fewest UNNEEDED fan-out branches, then the
        # narrowest. Plain "narrowest" picks case_communications for a patient lookup —
        # smallest, but it hauls in the emails branch for no reason.
        def key(v: str):
            return (len(branches_of.get(v, set()) - needed), sizes.get(v, 10**6), v)

        chosen = min(candidates, key=key)
        return chosen, {
            "candidates": candidates,
            "chosen": chosen,
            "fallback": False,
            "requested_fields": sorted(fields),
            "needed_branches": sorted(needed),
            "unneeded_branches": sorted(branches_of.get(chosen, set()) - needed),
            "ranking": {v: {"unneeded": len(branches_of.get(v, set()) - needed),
                            "size": sizes.get(v)} for v in candidates},
        }

    # Nothing covers everything — fall back to the widest view and report what it misses.
    fallback = "master_hospital_360"
    covered = names_per_view.get(fallback, set())
    return fallback, {
        "candidates": [],
        "chosen": fallback,
        "fallback": True,
        "requested_fields": sorted(fields),
        "uncovered_fields": sorted(fields - covered),
        "coverage_by_view": {v: len(fields & names_per_view.get(v, set())) for v in ALLOWED_VIEWS},
    }


def requalify(qnames: list[str], view: str, catalog: list[Member]) -> list[str]:
    """Re-point selected members onto the chosen view, dropping any it does not expose."""
    valid = {m.name for m in catalog if m.view == view}
    out = []
    for q in qnames:
        fname = q.split(".", 1)[-1]
        if fname in valid:
            out.append(f"{view}.{fname}")
    return out


def render_menu(members: list[Member]) -> str:
    """Menu block for the SQL prompt, grouped by kind so the model can see at a glance
    what may go in SELECT vs WHERE."""
    lines = []
    for kind, label in (("measure", "MEASURES (pre-aggregated — never wrap in SUM/COUNT/AVG)"),
                        ("dimension", "DIMENSIONS (SELECT / WHERE / GROUP BY)"),
                        ("segment", "SEGMENTS (boolean — WHERE only, e.g. WHERE <name> = true)")):
        group = [m for m in members if m.kind == kind]
        if group:
            lines.append(f"\n{label}:")
            lines.extend(m.render() for m in group)
    return "\n".join(lines)
