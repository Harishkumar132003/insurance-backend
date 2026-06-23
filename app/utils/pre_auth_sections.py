"""Mapping between the nested pre-auth form sections (API shape) and the flat
typed columns (pre_auth_patient / pre_auth_treatment / pre_auth_hospitalization).

The API carries the same nested section shape the frontend already builds
(`patient_insured`, `treating_doctor`, `hospitalization`), but storage is fully
typed columns — `form_data.data_json` is no longer used for pre-auth.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models.form_data import FormData
from app.models.pre_auth_patient import PreAuthPatient
from app.models.pre_auth_treatment import PreAuthTreatment
from app.models.pre_auth_hospitalization import PreAuthHospitalization


# (column, json_key) for flat fields
_PATIENT_FIELDS = [
    "patient_name", "gender", "address", "age_years", "occupation", "employee_id",
    "date_of_birth", "policy_number", "contact_number", "corporate_name",
    "insured_card_id", "has_other_insurance", "has_family_physician",
    "family_physician_name", "family_physician_contact", "other_insurance_company",
    "other_insurance_details", "relative_contact_number",
]
_PATIENT_DATE_FIELDS = {"date_of_birth"}
_PATIENT_INT_FIELDS = {"age_years"}
_PATIENT_BOOL_FIELDS = {"has_other_insurance", "has_family_physician"}

_TREATMENT_FLAT = [
    "doctor_name", "provisional_diagnosis", "icd10_code", "surgery_name",
    "surgery_icd_code", "drug_route", "injury_cause", "past_history",
    "duration_days", "other_treatment", "critical_findings", "treatment_details",
    "illness_description", "first_consultation_date",
]
_TREATMENT_DATE_FIELDS = {"first_consultation_date"}
_TREATMENT_INT_FIELDS = {"duration_days"}
# column -> (sub-object key, leaf key)
_TREATMENT_PLAN = {
    "tp_investigation": "investigation",
    "tp_intensive_care": "intensive_care",
    "tp_non_allopathic": "non_allopathic",
    "tp_medical_management": "medical_management",
    "tp_surgical_management": "surgical_management",
}
_ACCIDENT = {
    "ad_is_rta": ("is_rta", bool),
    "ad_substance_abuse": ("substance_abuse", bool),
    "ad_reported_to_police": ("reported_to_police", bool),
    "ad_test_conducted": ("test_conducted", str),
}

_HOSP_FLAT = ["room_type", "is_emergency", "icu_days", "expected_days", "admission_date", "admission_time"]
_HOSP_DATE_FIELDS = {"admission_date"}
_HOSP_INT_FIELDS = {"icu_days", "expected_days"}
_HOSP_BOOL_FIELDS = {"is_emergency"}
_HOSP_COSTS = [
    "room_rent", "ot_charges", "icu_charges", "medicines_cost", "investigation_cost",
    "professional_fees", "package_charges", "other_expenses", "total_cost",
]
_HOSP_CHRONIC = {
    "cc_diabetes": "diabetes", "cc_hypertension": "hypertension",
    "cc_heart_disease": "heart_disease", "cc_asthma_copd": "asthma_copd",
    "cc_cancer": "cancer", "cc_hiv_std": "hiv_std",
    "cc_hyperlipidemia": "hyperlipidemia", "cc_osteoarthritis": "osteoarthritis",
    "cc_alcohol_drug_abuse": "alcohol_drug_abuse",
}


def _to_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _to_int(v):
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_bool(v):
    if v in (None, ""):
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Write: nested sections → typed columns ─────────────────────────

def apply_sections(db: Session, form_data: FormData, sections: dict) -> None:
    """Upsert the three child rows for this form_data from the nested
    `sections` dict ({patient_insured, treating_doctor, hospitalization}).
    Only sections present in the dict are touched (partial update friendly)."""
    sections = sections or {}

    if "patient_insured" in sections:
        pi = sections.get("patient_insured") or {}
        row = form_data.patient or PreAuthPatient(form_data_id=form_data.id)
        for f in _PATIENT_FIELDS:
            if f not in pi:
                continue
            val = pi.get(f)
            if f in _PATIENT_DATE_FIELDS:
                val = _to_date(val)
            elif f in _PATIENT_INT_FIELDS:
                val = _to_int(val)
            elif f in _PATIENT_BOOL_FIELDS:
                val = _to_bool(val)
            setattr(row, f, val)
        if form_data.patient is None:
            db.add(row)
            form_data.patient = row

    if "treating_doctor" in sections:
        td = sections.get("treating_doctor") or {}
        row = form_data.treatment or PreAuthTreatment(form_data_id=form_data.id)
        for f in _TREATMENT_FLAT:
            if f not in td:
                continue
            val = td.get(f)
            if f in _TREATMENT_DATE_FIELDS:
                val = _to_date(val)
            elif f in _TREATMENT_INT_FIELDS:
                val = _to_int(val)
            setattr(row, f, val)
        plan = td.get("treatment_plan")
        if isinstance(plan, dict):
            for col, key in _TREATMENT_PLAN.items():
                if key in plan:
                    setattr(row, col, _to_bool(plan.get(key)))
        acc = td.get("accident_details")
        if isinstance(acc, dict):
            for col, (key, kind) in _ACCIDENT.items():
                if key in acc:
                    setattr(row, col, _to_bool(acc.get(key)) if kind is bool else acc.get(key))
        if form_data.treatment is None:
            db.add(row)
            form_data.treatment = row

    if "hospitalization" in sections:
        h = sections.get("hospitalization") or {}
        row = form_data.hospitalization or PreAuthHospitalization(form_data_id=form_data.id)
        for f in _HOSP_FLAT:
            if f not in h:
                continue
            val = h.get(f)
            if f in _HOSP_DATE_FIELDS:
                val = _to_date(val)
            elif f in _HOSP_INT_FIELDS:
                val = _to_int(val)
            elif f in _HOSP_BOOL_FIELDS:
                val = _to_bool(val)
            setattr(row, f, val)
        costs = h.get("costs")
        if isinstance(costs, dict):
            for f in _HOSP_COSTS:
                if f in costs:
                    setattr(row, f, _num(costs.get(f)))
        # Derived room costs: room_rent and icu_charges are per-day rates;
        # room_rent applies to non-ICU days, icu_charges to ICU days. Computed from
        # the row (post-setattr) so it stays consistent on partial edits too.
        icu_days = row.icu_days or 0
        non_icu_days = max(0, (row.expected_days or 0) - icu_days)
        row.room_rent_total = float(row.room_rent or 0) * non_icu_days
        row.icu_charges_total = float(row.icu_charges or 0) * icu_days
        chronic = h.get("chronic_conditions")
        if isinstance(chronic, dict):
            for col, key in _HOSP_CHRONIC.items():
                if key in chronic:
                    setattr(row, col, _to_bool(chronic.get(key)))
        if form_data.hospitalization is None:
            db.add(row)
            form_data.hospitalization = row


# ── Read: typed columns → nested sections ──────────────────────────

def _iso(v):
    return v.isoformat() if v is not None else None


def compose_sections(form_data: FormData) -> dict:
    """Build the nested section dict (API shape) from the typed columns.
    Returns {} keys absent when a section row doesn't exist."""
    out: dict = {}

    p = form_data.patient
    if p is not None:
        out["patient_insured"] = {
            "patient_name": p.patient_name,
            "gender": p.gender,
            "address": p.address,
            "age_years": p.age_years,
            "occupation": p.occupation,
            "employee_id": p.employee_id,
            "date_of_birth": _iso(p.date_of_birth),
            "policy_number": p.policy_number,
            "contact_number": p.contact_number,
            "corporate_name": p.corporate_name,
            "insured_card_id": p.insured_card_id,
            "has_other_insurance": p.has_other_insurance,
            "has_family_physician": p.has_family_physician,
            "family_physician_name": p.family_physician_name,
            "family_physician_contact": p.family_physician_contact,
            "other_insurance_company": p.other_insurance_company,
            "other_insurance_details": p.other_insurance_details,
            "relative_contact_number": p.relative_contact_number,
        }

    t = form_data.treatment
    if t is not None:
        out["treating_doctor"] = {
            "doctor_name": t.doctor_name,
            "provisional_diagnosis": t.provisional_diagnosis,
            "icd10_code": t.icd10_code,
            "surgery_name": t.surgery_name,
            "surgery_icd_code": t.surgery_icd_code,
            "drug_route": t.drug_route,
            "injury_cause": t.injury_cause,
            "past_history": t.past_history,
            "duration_days": t.duration_days,
            "other_treatment": t.other_treatment,
            "critical_findings": t.critical_findings,
            "treatment_details": t.treatment_details,
            "illness_description": t.illness_description,
            "first_consultation_date": _iso(t.first_consultation_date),
            "treatment_plan": {
                "investigation": t.tp_investigation,
                "intensive_care": t.tp_intensive_care,
                "non_allopathic": t.tp_non_allopathic,
                "medical_management": t.tp_medical_management,
                "surgical_management": t.tp_surgical_management,
            },
            "accident_details": {
                "is_rta": t.ad_is_rta,
                "substance_abuse": t.ad_substance_abuse,
                "reported_to_police": t.ad_reported_to_police,
                "test_conducted": t.ad_test_conducted,
            },
        }

    h = form_data.hospitalization
    if h is not None:
        out["hospitalization"] = {
            "room_type": h.room_type,
            "is_emergency": h.is_emergency,
            "icu_days": h.icu_days,
            "expected_days": h.expected_days,
            "admission_date": _iso(h.admission_date),
            "admission_time": h.admission_time,
            "costs": {
                "room_rent": _num(h.room_rent),
                "ot_charges": _num(h.ot_charges),
                "icu_charges": _num(h.icu_charges),
                "medicines_cost": _num(h.medicines_cost),
                "investigation_cost": _num(h.investigation_cost),
                "professional_fees": _num(h.professional_fees),
                "package_charges": _num(h.package_charges),
                "other_expenses": _num(h.other_expenses),
                "total_cost": _num(h.total_cost),
                # Derived (server-computed); read-only — not in _HOSP_COSTS.
                "room_rent_total": _num(h.room_rent_total),
                "icu_charges_total": _num(h.icu_charges_total),
            },
            "chronic_conditions": {
                "diabetes": h.cc_diabetes,
                "hypertension": h.cc_hypertension,
                "heart_disease": h.cc_heart_disease,
                "asthma_copd": h.cc_asthma_copd,
                "cancer": h.cc_cancer,
                "hiv_std": h.cc_hiv_std,
                "hyperlipidemia": h.cc_hyperlipidemia,
                "osteoarthritis": h.cc_osteoarthritis,
                "alcohol_drug_abuse": h.cc_alcohol_drug_abuse,
            },
        }

    return out
