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
            "hospitalization_id": {"d": "FK -> hospitalization.id (the case)."},
            "hospital_id": {"d": "FK -> hospitals.id (the case's hospital; denormalised)."},
            "preauth_status": {"d": "The case's PRE-AUTH workflow status mirrored onto the PRE_AUTH row, FROZEN once the claim is raised. Use for 'pre-auth status' questions.", "enum": _PREAUTH_STATUS_ENUM},
            "preauth_raised_amount": {"d": "Original pre-auth requested amount (the cost-estimate total)."},
            "preauth_approved_amount": {"d": "Pre-auth approved amount (mirrors hospitalization.approved_amount)."},
        },
    },
    "patient_personal_detail": {
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
            "hospitalization_id": {"d": "FK -> hospitalization.id (the case). Count DISTINCT of this for 'pre-auths converted to claims'."},
            "hospital_id": {"d": "FK -> hospitals.id (the case's hospital; denormalised)."},
            "uhid": {"d": "Patient UHID (denormalised from the case)."},
            "claim_number": {"d": "Insurer claim/authorization number (denormalised from the case)."},
            "claimed_amount": {"d": "Amount claimed in the claim submission (money)."},
            "approved_amount": {"d": "Claim-stage approved amount (money)."},
            "status": {"d": "Claim status, CLAIM_-prefixed.", "enum": ["CLAIM_SUBMITTED", "CLAIM_ADR_SUBMITTED", "CLAIM_RECONSIDER", "CLAIM_ADR_NMI", "CLAIM_APPROVED", "CLAIM_PARTIALLY_APPROVED", "CLAIM_DENIED", "CLAIM_UNKNOWN"]},
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
            "hospitalization_id": {"d": "FK -> hospitalization.id (the case; may be NULL if unmatched)."},
            "claim_number": {"d": "Insurer claim number on the remittance."},
            "settled_amount": {"d": "Amount settled/paid for this claim (money; SUM for 'settled/paid amount')."},
            "claim_raised_amount": {"d": "Amount that had been claimed/raised."},
            "disallowance": {"d": "Amount disallowed (raised minus settled)."},
            "is_matched": {"d": "Whether this line was matched to a known case.", "enum": ["true", "false"]},
            "hospital_id": {"d": "FK -> hospitals.id (the batch's hospital; denormalised, always set)."},
            "uhid": {"d": "Patient UHID of the matched case (denormalised; NULL when unmatched)."},
        },
    },
    "preauth_status_tracking": {
        "desc": "PRE-AUTH status-transition log (for status/turn-around-time questions). One case -> MANY rows; never fan out through it when counting cases.",
        "cols": {
            "hospitalization_id": {"d": "FK -> hospitalization.id (the case). NON-unique — many rows per case."},
            "hospital_id": {"d": "FK -> hospitals.id (the case's hospital; denormalised)."},
            "uhid": {"d": "Patient UHID (denormalised)."},
            "email_id": {"d": "FK -> claim_case_emails.id — the email that drove this transition (join for email type/subject/ai_suggested_*)."},
            "from_status": {"d": "Status before the change (NULL for the very first; first logged row is DRAFT->SUBMITTED)."},
            "to_status": {"d": "Status after the change."},
            "turn_around_time": {"d": "Interval spent from_status -> to_status (e.g. '1 day 00:20:30'). EXTRACT(EPOCH FROM ...) to aggregate/average."},
            "turn_around_time_text": {"d": "Human-readable TAT, e.g. '1 day 2 min 20 sec', '55 sec'. Use for display; use turn_around_time for math."},
            "document_link": {"d": "JSONB array of file paths on the status's email — both email attachments and uploaded case documents (NULL when none)."},
            "remark": {"d": "Free-text note for the transition."},
            "created_at": {"d": "When the transition happened — order by this for the timeline."},
        },
    },
    "claim_status_tracking": {
        "desc": "CLAIM status-transition log (for claim status/turn-around-time questions). One case -> MANY rows; never fan out through it when counting cases.",
        "cols": {
            "hospitalization_id": {"d": "FK -> hospitalization.id (the case). NON-unique — many rows per case."},
            "hospital_id": {"d": "FK -> hospitals.id (the case's hospital; denormalised)."},
            "uhid": {"d": "Patient UHID (denormalised)."},
            "claim_number": {"d": "Insurer claim/authorization number (denormalised)."},
            "email_id": {"d": "FK -> claim_case_emails.id — the email that drove this transition."},
            "from_status": {"d": "Status before the change, CLAIM_-prefixed (NULL for the first; first logged row is CLAIM_SUBMITTED)."},
            "to_status": {"d": "Claim-stage status after the change, always CLAIM_-prefixed: CLAIM_SUBMITTED, CLAIM_APPROVED, CLAIM_PARTIALLY_APPROVED, CLAIM_DENIED, CLAIM_ADR_SUBMITTED, CLAIM_ADR_NMI, CLAIM_CANCELLED."},
            "turn_around_time": {"d": "Interval spent from_status -> to_status. EXTRACT(EPOCH FROM ...) to aggregate/average."},
            "turn_around_time_text": {"d": "Human-readable TAT, e.g. '1 day 2 min 20 sec'. Use for display; use turn_around_time for math."},
            "document_link": {"d": "JSONB array of file paths on the status's email — attachments + uploaded case documents (NULL when none)."},
            "remark": {"d": "The claim remark for this transition."},
            "created_at": {"d": "When the transition happened — order by this for the timeline."},
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
        "desc": "Per-line claim bill breakdown (label + amount), one claim per case.",
        "cols": {
            "hospitalization_id": {"d": "FK -> hospitalization.id (the case)."},
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
