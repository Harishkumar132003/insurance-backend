"""Semantic "cube" catalog for the AI query agent.

For each table we keep CURATED meaning — a one-line table description plus, per
column, a human description and (where relevant) the enum of allowed values.
Column names and types are pulled LIVE from information_schema at render time and
the curated text is overlaid, so this file can never make the schema "lie" about
columns/types — it only adds meaning.

`render_cubes(table_names)` returns a compact, LLM-friendly block for ONLY the
given tables — the agent flow feeds it the planner-selected tables so the
executor sees rich detail for exactly what it needs.
"""

import logging
from collections import defaultdict

from sqlalchemy import text

from app.db.session import engine

logger = logging.getLogger(__name__)

# --- curated semantics: {table: {"desc", "cols": {col: {"d", "enum"?}}}} -------
_CASE_STATUS_ENUM = [
    "DRAFT", "SUBMITTED", "ENHANCE_SUBMITTED", "RECONSIDER", "ADR_SUBMITTED",
    "APPROVED", "PARTIALLY_APPROVED", "DENIED", "ENHANCEMENT_APPROVED",
    "ENHANCEMENT_DENIED", "CANCELLED",
    "CLAIM_SUBMITTED", "CLAIM_ADR_SUBMITTED", "CLAIM_RECONSIDER",
    "CLAIM_APPROVED", "CLAIM_PARTIALLY_APPROVED",
]
_PREAUTH_OUTCOME_ENUM = [
    "APPROVED", "PARTIALLY_APPROVED", "DENIED", "ENHANCEMENT_APPROVED",
    "ENHANCEMENT_DENIED", "ADR_NMI", "CANCELLED",
]
_PREAUTH_STATUS_ENUM = [
    "DRAFT", "SUBMITTED", "ENHANCE_SUBMITTED", "RECONSIDER", "ADR_SUBMITTED",
    "APPROVED", "PARTIALLY_APPROVED", "DENIED", "ENHANCEMENT_APPROVED",
    "ENHANCEMENT_DENIED", "CANCELLED",
]

TABLE_DOCS: dict = {
    "hospitalization": {
        "desc": "THE CLAIM-CASE HUB — one row per case; holds the case's LIVE state.",
        "cols": {
            "id": {"d": "Case id (claim_case_id everywhere else points here)."},
            "uhid": {"d": "Hospital case/patient identifier — an ID, NOT the patient name."},
            "claim_number": {"d": "Insurer claim / authorization number."},
            "current_stage": {"d": "Which phase the case is in.", "enum": ["PRE_AUTH", "CLAIM"]},
            "case_status": {"d": "LIVE overall workflow state (pre-auth or claim phase). Use for live status / 'awaiting insurer' (SUBMITTED, ENHANCE_SUBMITTED, RECONSIDER, ADR_SUBMITTED, CLAIM_SUBMITTED, CLAIM_ADR_SUBMITTED, CLAIM_RECONSIDER).", "enum": _CASE_STATUS_ENUM},
            "preauth_outcome": {"d": "FINAL pre-auth DECISION only (use for approved/denied/partially-approved case questions).", "enum": _PREAUTH_OUTCOME_ENUM},
            "approved_amount": {"d": "Cumulative pre-auth amount approved by the insurer (money; SUM for 'approved amount')."},
            "created_at": {"d": "Case creation time — use for 'this month'/'this year' filters."},
        },
    },
    "pre_auth": {
        "desc": "Pre-auth/claim FORM snapshot. One PRE_AUTH row per case, plus a CLAIM row when a claim is raised. Has MULTIPLE rows per case — never fan out through it when counting cases.",
        "cols": {
            "claim_case_id": {"d": "FK -> hospitalization.id."},
            "stage": {"d": "Which phase this snapshot belongs to.", "enum": ["PRE_AUTH", "CLAIM"]},
            "draft_state": {"d": "FORM lifecycle ONLY (is the form drafted/submitted) — NOT the outcome.", "enum": ["DRAFT", "SUBMITTED"]},
            "preauth_status": {"d": "The case's PRE-AUTH workflow status mirrored onto the PRE_AUTH row, FROZEN once the claim is raised. Use for 'pre-auth status' questions.", "enum": _PREAUTH_STATUS_ENUM},
            "claimed_amount": {"d": "Claim-stage claimed amount (NULL for pre-auth rows)."},
            "remarks": {"d": "Free-text remarks."},
        },
    },
    "pre_auth_patient": {
        "desc": "Patient/insured details for a pre_auth form. THE ONLY place patient_name lives.",
        "cols": {
            "form_data_id": {"d": "FK -> pre_auth.id (join patients via this, NOT via uhid)."},
            "patient_name": {"d": "Patient full name. Match case-insensitively with ILIKE."},
            "policy_number": {"d": "Insurance policy number."},
            "insured_card_id": {"d": "Insurer card / member id."},
            "date_of_birth": {"d": "Patient date of birth."},
            "gender": {"d": "Patient gender."},
        },
    },
    "pre_auth_stay": {
        "desc": "Hospitalisation stay + requested cost breakdown for a pre_auth form (one per form).",
        "cols": {
            "form_data_id": {"d": "FK -> pre_auth.id."},
            "total_cost": {"d": "Total REQUESTED / estimated pre-auth cost (money). Use for 'requested/estimated cost'."},
            "room_rent": {"d": "Requested room rent."},
            "icu_charges": {"d": "Requested ICU charges."},
            "admission_date": {"d": "Planned/actual admission date."},
            "room_type": {"d": "Room category requested."},
        },
    },
    "pre_auth_treatment": {
        "desc": "Diagnosis & treatment details for a pre_auth form (one per form).",
        "cols": {
            "form_data_id": {"d": "FK -> pre_auth.id."},
            "doctor_name": {"d": "Treating doctor."},
            "provisional_diagnosis": {"d": "Provisional diagnosis text."},
            "icd10_code": {"d": "ICD-10 diagnosis code."},
            "surgery_name": {"d": "Planned surgery/procedure."},
        },
    },
    "claims": {
        "desc": "Final claim (post pre-auth) per case. One row per claim.",
        "cols": {
            "claim_case_id": {"d": "FK -> hospitalization.id. Count DISTINCT of this for 'pre-auths converted to claims'."},
            "claimed_amount": {"d": "Amount claimed in the claim submission (money)."},
            "approved_amount": {"d": "Claim-stage approved amount (money)."},
            "status": {"d": "Claim status.", "enum": ["SUBMITTED", "APPROVED", "PARTIALLY_APPROVED", "DENIED"]},
            "submitted_at": {"d": "When the claim was submitted."},
            "created_at": {"d": "Claim row creation time."},
        },
    },
    "settlement_batch": {
        "desc": "Settlement HEADER — one row per remittance batch from a TPA/insurer. (Invoice/payment questions are settlement questions.)",
        "cols": {
            "hospital_id": {"d": "FK -> hospitals.id (tenant)."},
            "tpa_insurer": {"d": "TPA / insurer that paid the batch."},
            "total_settlement_amount": {"d": "Batch total settled (money). To total settlements: SUM this from settlement_batch ALONE (no join), or SUM settlement_item.settled_amount."},
            "settlement_date": {"d": "Date the settlement/payment was made — use for date-filtered settlement questions."},
            "utr_number": {"d": "Bank UTR / payment reference."},
            "payment_mode": {"d": "Payment mode (NEFT/RTGS/etc)."},
        },
    },
    "settlement_item": {
        "desc": "Settlement LINE — one row per claim within a settlement batch. Has settled_amount per claim.",
        "cols": {
            "batch_id": {"d": "FK -> settlement_batch.id (join here to get settlement_date/insurer)."},
            "claim_case_id": {"d": "FK -> hospitalization.id (may be NULL if unmatched)."},
            "claim_number": {"d": "Insurer claim number on the remittance."},
            "settled_amount": {"d": "Amount settled/paid for this claim (money; SUM for 'settled/paid amount')."},
            "claim_raised_amount": {"d": "Amount that had been claimed/raised."},
            "disallowance": {"d": "Amount disallowed (raised minus settled)."},
            "is_matched": {"d": "Whether this line was matched to a known case.", "enum": ["true", "false"]},
        },
    },
    "status_history": {
        "desc": "Audit timeline — one row per status change of a case. Use for per-round history/trends.",
        "cols": {
            "claim_case_id": {"d": "FK -> hospitalization.id."},
            "stage": {"d": "Phase at the time of the change.", "enum": ["PRE_AUTH", "CLAIM"]},
            "status": {"d": "The status set at this step.", "enum": _CASE_STATUS_ENUM},
            "approved_amount": {"d": "Amount approved AT this round (per-round, not cumulative)."},
            "created_at": {"d": "When this status change happened."},
            "remarks": {"d": "Free-text note for the change."},
        },
    },
    "claim_case_emails": {
        "desc": "Email correspondence with the insurer/TPA for a case (incoming & outgoing), plus AI-extracted fields.",
        "cols": {
            "claim_case_id": {"d": "FK -> hospitalization.id."},
            "direction": {"d": "Email direction.", "enum": ["INBOUND", "OUTBOUND"]},
            "email_type": {"d": "Workflow type of the email (SUBMITTED/ADR/APPROVED/etc)."},
            "subject": {"d": "Email subject."},
            "email_date": {"d": "Email timestamp."},
            "ai_suggested_amount": {"d": "Amount the AI extracted from the insurer email (money)."},
            "ai_suggested_status": {"d": "Outcome the AI extracted from the email."},
        },
    },
    "claim_bill_item": {
        "desc": "Per-line bill breakdown on a claim-stage pre_auth row (label + amount).",
        "cols": {
            "form_data_id": {"d": "FK -> pre_auth.id."},
            "label": {"d": "Bill line label (e.g. room rent, pharmacy)."},
            "amount": {"d": "Line amount (money)."},
        },
    },
    "hospital_provider_mappings": {
        "desc": "Which insurers/TPAs this hospital is empanelled with, incl. MoU room-charge terms.",
        "cols": {
            "hospital_id": {"d": "FK -> hospitals.id."},
            "policy_provider_id": {"d": "FK -> policy_provider_configs.id (the insurer/TPA)."},
            "is_active": {"d": "Whether the empanelment is active.", "enum": ["true", "false"]},
            "room_charges": {"d": "Agreed room-charge terms (JSON)."},
        },
    },
    "hospitals": {
        "desc": "The hospital record itself (one row for the tenant).",
        "cols": {
            "name": {"d": "Hospital name."},
            "rohini_id": {"d": "ROHINI registration id."},
            "email": {"d": "Hospital contact email."},
        },
    },
    "settlements": {
        "desc": "DEPRECATED and empty — do NOT use. Settlements live in settlement_batch + settlement_item.",
        "cols": {},
    },
}

_TYPE_SHORT = {
    "character varying": "string", "text": "text", "uuid": "uuid",
    "timestamp with time zone": "timestamptz", "timestamp without time zone": "timestamp",
    "date": "date", "boolean": "bool", "numeric": "numeric",
    "bigint": "int", "integer": "int", "smallint": "int", "jsonb": "jsonb",
    "double precision": "float",
}

_LIVE_CACHE: dict = {}


def _short_type(dt: str) -> str:
    return _TYPE_SHORT.get(dt, dt)


def _live_schema(table_names: list[str]) -> dict:
    """Live columns + FKs for the given tables (cached per process)."""
    missing = [t for t in table_names if t not in _LIVE_CACHE]
    if missing:
        with engine.connect() as conn:
            cols = conn.execute(text(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name = ANY(:t) "
                "ORDER BY table_name, ordinal_position"
            ), {"t": missing}).fetchall()
            fks = conn.execute(text(
                "SELECT tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema "
                "JOIN information_schema.constraint_column_usage ccu "
                "  ON ccu.constraint_name=tc.constraint_name AND ccu.table_schema=tc.table_schema "
                "WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public' "
                "  AND tc.table_name = ANY(:t)"
            ), {"t": missing}).fetchall()
        cmap = defaultdict(list)
        fmap = defaultdict(dict)
        for tn, cn, dt in cols:
            cmap[tn].append((cn, dt))
        for tn, cn, ft, fc in fks:
            fmap[tn][cn] = f"{ft}.{fc}"
        for t in missing:
            _LIVE_CACHE[t] = {"columns": cmap.get(t, []), "fks": dict(fmap.get(t, {}))}
    return {t: _LIVE_CACHE[t] for t in table_names if t in _LIVE_CACHE and _LIVE_CACHE[t]["columns"]}


def render_cubes(table_names: list[str]) -> str:
    """Compact, LLM-friendly semantic cube for the given tables only."""
    live = _live_schema(table_names)
    out: list[str] = []
    for t in table_names:
        if t not in live:
            continue
        doc = TABLE_DOCS.get(t, {})
        header = f"TABLE {t}"
        if doc.get("desc"):
            header += f" — {doc['desc']}"
        out.append(header)
        coldocs = doc.get("cols", {})
        for name, dtype in live[t]["columns"]:
            line = f"  {name} {_short_type(dtype)}"
            cd = coldocs.get(name, {})
            if cd.get("d"):
                line += f" — {cd['d']}"
            if cd.get("enum"):
                line += f" [enum: {', '.join(cd['enum'])}]"
            fk = live[t]["fks"].get(name)
            if fk and "FK" not in cd.get("d", ""):
                line += f" (FK->{fk})"
            out.append(line)
        out.append("")
    return "\n".join(out).rstrip()
