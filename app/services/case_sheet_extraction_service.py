"""Extract pre-auth form data from a hospital case sheet PDF.

An alternative to the UHID workflow on the "Fill with AI" screen: the user
uploads the case sheet and we pull out the same fields the workflow would have
returned. Mirrors mou_extraction_service — strict JSON schema, temperature 0,
and a swallow-and-fallback posture so a bad document still lands the user on a
fillable form instead of an error page.

The scalar keys below are named EXACTLY as the frontend's FORM_SECTIONS field
keys, so the existing keyToSection mapping routes each one into the right
section/subgroup with no extra wiring.
"""
import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

from app.core.config import settings
from app.utils.pdf_text import extract_text

logger = logging.getLogger(__name__)

# What a case sheet may be uploaded as. Checked server-side: the browser's
# `accept` attribute is trivially bypassed.
PDF_CONTENT_TYPE = "application/pdf"
IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_CONTENT_TYPES = {PDF_CONTENT_TYPE} | IMAGE_CONTENT_TYPES
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}

MAX_FILES = 10
MAX_FILE_BYTES = 10 * 1024 * 1024

# Each page image is its own API call rather than many images in one.
# Measured on gpt-4o-mini: one high-detail image costs ~25-48k prompt tokens
# depending on aspect ratio, so even three or four would approach the 128k
# context window. Splitting keeps every call comfortably inside it; the token
# total (and therefore the cost) is the same either way.
_PAGE_WORKERS = 4

# Route codes offered by the form's Drug Route multi-select. Duplicated from the
# frontend's DRUG_ROUTES because the model would otherwise invent codes; anything
# outside this set is dropped.
_DRUG_ROUTE_CODES = [
    "PO", "IV", "IM", "SC", "ID", "SL", "BUCCAL", "TOP", "TD", "INH", "NEB",
    "NASAL", "OPH", "OTIC", "RECTAL", "VAGINAL", "PR", "PEG", "NG",
    "INTRA_ART", "INTRATHECAL", "EPIDURAL", "INTRAPERITONEAL", "INTRAVESICAL",
    "INTRAOCULAR",
]

# Category -> its investigations, mirroring the InvestigationCategory /
# Investigation enums and the form's own cascading dropdown. The pairing matters:
# the form narrows the Investigation options by the chosen Category, so a name
# filed under the wrong category would render as a "(custom)" stand-in.
_INVESTIGATIONS_BY_CATEGORY = {
    "HEMATOLOGY": [
        "CBC", "HEMOGLOBIN", "TOTAL_WBC_COUNT", "DIFFERENTIAL_COUNT",
        "PLATELET_COUNT", "ESR", "PERIPHERAL_SMEAR", "MP_SMEAR", "PT_INR", "APTT",
    ],
    "BIOCHEMISTRY": [
        "RBS", "FBS", "PPBS", "HBA1C", "SERUM_ELECTROLYTES", "SERUM_CREATININE",
        "BLOOD_UREA", "LFT", "RFT", "LIPID_PROFILE", "SERUM_CALCIUM", "CRP",
        "PROCALCITONIN", "ABG",
    ],
    "MICROBIOLOGY": [
        "BLOOD_CULTURE_SENSITIVITY", "URINE_CULTURE_SENSITIVITY", "SPUTUM_CULTURE",
        "CSF_ANALYSIS", "STOOL_ROUTINE_CULTURE", "WOUND_SWAB_CULTURE",
    ],
    "SEROLOGY_IMMUNOLOGY": [
        "DENGUE_NS1_IGM", "WIDAL_TYPHIDOT", "HIV", "HBSAG", "ANTI_HCV", "COVID_RTPCR",
    ],
    "URINE_ANALYSIS": ["URINE_ROUTINE", "URINE_KETONES"],
    "RADIOLOGY_IMAGING": [
        "XRAY_CHEST", "XRAY_ABDOMEN", "XRAY_LIMB", "USG_ABDOMEN", "USG_KUB",
        "CT_BRAIN", "CT_ABDOMEN", "CT_CHEST", "MRI_BRAIN", "MRI_SPINE",
    ],
    "CARDIOLOGY": ["ECG", "ECHO", "TMT", "TROPONIN_I"],
    "NEUROLOGY": ["EEG", "NCS_EMG"],
    "HISTOPATHOLOGY": ["BIOPSY_HPE", "FNAC"],
    "OTHERS": ["OTHERS"],
}

_INVESTIGATION_CATEGORIES = list(_INVESTIGATIONS_BY_CATEGORY)
_INVESTIGATION_NAMES = [n for names in _INVESTIGATIONS_BY_CATEGORY.values() for n in names]
# name -> the category that actually owns it, so a mis-filed pair can be corrected.
_CATEGORY_OF = {
    name: category
    for category, names in _INVESTIGATIONS_BY_CATEGORY.items()
    for name in names
}

# Flat scalar fields, grouped only for readability — the model returns them at
# the top level. (key, json-type) where the type is the non-null half.
_TEXT_FIELDS = [
    "uhid",
    # patient_insured
    "patient_name", "gender", "date_of_birth", "contact_number",
    "relative_contact_number", "address", "occupation",
    # treating_doctor
    "doctor_name", "doctor_contact", "provisional_diagnosis",
    "illness_description", "critical_findings", "past_history",
    "first_consultation_date",
    # accident_details
    "injury_date", "fir_number", "test_conducted",
    # hospitalization
    "admission_date", "admission_time", "room_type",
]
_NUMBER_FIELDS = ["age_years", "duration_days", "expected_days", "icu_days"]
_BOOL_FIELDS = [
    # treatment_plan
    "medical_management", "surgical_management", "intensive_care",
    "investigation", "non_allopathic",
    # accident
    "has_accident", "is_rta", "reported_to_police", "substance_abuse",
    # chronic_conditions
    "diabetes", "heart_disease", "hypertension", "hyperlipidemia",
    "osteoarthritis", "asthma_copd", "cancer", "alcohol_drug_abuse", "hiv_std",
]

_SCALAR_FIELDS = _TEXT_FIELDS + _NUMBER_FIELDS + _BOOL_FIELDS


CONFIDENCE_LEVELS = ["HIGH", "MEDIUM", "LOW"]

# Provenance longer than this is a paraphrase or a whole paragraph, not a
# citation — truncated so the UI can show it on one line.
_MAX_SOURCE_CHARS = 120


def _scored(value_type: list[str]) -> dict:
    """One scalar field as {value, confidence, source}.

    Value and evidence are requested together on purpose: a source snippet asked
    for separately tends to be reconstructed after the fact rather than quoted.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["value", "confidence", "source"],
        "properties": {
            "value": {"type": value_type},
            "confidence": {
                "type": ["string", "null"],
                "enum": CONFIDENCE_LEVELS + [None],
                "description": "How much to trust this value, based on how directly "
                               "the sheet stated it. HIGH = copied verbatim from an "
                               "explicit label; MEDIUM = stated but reformatted or "
                               "interpreted; LOW = inferred from prose.",
            },
            "source": {
                "type": ["string", "null"],
                "description": "The VERBATIM fragment of the case sheet this value "
                               "came from, copied character for character. Null if "
                               "no value was found. Never paraphrase.",
            },
        },
    }


def _schema() -> dict:
    props: dict = {
        "summary": {
            "type": "string",
            "description": "Short markdown summary of the case: who the patient is, "
                           "why they were admitted, and the planned treatment.",
        },
    }
    for key in _TEXT_FIELDS:
        props[key] = _scored(["string", "null"])
    for key in _NUMBER_FIELDS:
        props[key] = _scored(["number", "null"])
    for key in _BOOL_FIELDS:
        props[key] = _scored(["boolean", "null"])

    props["treatments"] = {
        "type": "array",
        "description": "One entry per distinct treatment or procedure described.",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["treatment_details", "drug_route", "surgery_icd_code", "injury_cause"],
            "properties": {
                "treatment_details": {"type": ["string", "null"]},
                "drug_route": {
                    "type": "array",
                    "items": {"type": "string", "enum": _DRUG_ROUTE_CODES},
                },
                "surgery_icd_code": {
                    "type": ["string", "null"],
                    "description": "7-character ICD-10-PCS procedure code, only if the "
                                   "sheet states one. Do not guess.",
                },
                "injury_cause": {"type": ["string", "null"]},
            },
        },
    }
    props["investigations"] = {
        "type": "array",
        "description": "Investigations ordered or reported in the sheet.",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["investigation_category", "investigation_name", "investigation_description"],
            "properties": {
                "investigation_category": {"type": "string", "enum": _INVESTIGATION_CATEGORIES},
                "investigation_name": {"type": "string", "enum": _INVESTIGATION_NAMES},
                "investigation_description": {
                    "type": ["string", "null"],
                    "description": "Finding or reason, if the sheet gives one.",
                },
            },
        },
    }

    return {
        "name": "case_sheet_extract",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            # OpenAI strict mode requires every property to be listed.
            "required": ["summary", "treatments", "investigations"] + _SCALAR_FIELDS,
            "properties": props,
        },
    }


_PROMPT = """You are reading an Indian hospital CASE SHEET to pre-fill a cashless \
pre-authorisation (Part C) form.

Extract only what the document actually states. Use null for anything absent — \
do NOT infer, estimate or invent values, and never carry over an example.

Every scalar field is an object: {{"value": …, "confidence": …, "source": …}}.

- `confidence` — how much a reviewer should trust the value, judged by how \
DIRECTLY the sheet stated it (not by whether it seems clinically plausible). \
Decide it mechanically, by comparing your own `value` against your own `source`:
    HIGH   — the value appears INSIDE the source quote character for character.
             source "Patient Name: Rahul Kumar" -> value "Rahul Kumar"   (present)
    MEDIUM — the value is in the quote but you rewrote it: reformatted, parsed \
out, converted, or turned a phrase into true/false.
             source "12/03/2026" -> value "2026-03-12"        (rewritten)
             source "No cardiac disease." -> value false      (interpreted)
    LOW    — the value is not in the quote at all; you reasoned it out.
             source "pain ... for 2 days" -> value duration_days 2
  Every reformatted date and every boolean read off a negation is MEDIUM, not \
HIGH. If you have marked more than a handful of fields HIGH, re-check them \
against this test.
- `source` — copy the fragment of the case sheet the value came from, CHARACTER \
FOR CHARACTER, including its label. Keep it under {max_source} characters. Do not \
paraphrase, translate, tidy up spacing or summarise; it must appear in the text \
above exactly as you write it. If you cannot quote it, the value is a guess — \
return null for the value instead.
- When `value` is null, `confidence` and `source` must also be null.

Rules:
- Dates as YYYY-MM-DD. Times as HH:MM (24-hour).
- `age_years`, `duration_days`, `expected_days`, `icu_days`: plain numbers.
- Booleans: true only when the sheet affirms it, false when it explicitly denies \
it, null when it is silent. Comorbidities are usually listed under history — a \
condition that is simply not mentioned is null, not false.
- `provisional_diagnosis` is the working diagnosis; `illness_description` is the \
presenting complaint / history of present illness; `critical_findings` are \
abnormal vitals, examination or report findings.
- `treatments`: one entry per distinct treatment or procedure. `drug_route` is a \
list of administration-route codes drawn ONLY from the allowed list (IV, PO, \
NEB, …); leave it empty if the sheet does not say how drugs are given.
- `investigations`: only tests the sheet actually names, mapped to the allowed \
category/name codes. Skip any test that has no matching code.
- `summary`: 3-5 sentences of markdown a claims reviewer could read at a glance.

Case sheet text:
{text}
"""


def _empty() -> dict:
    return {"summary": "", "data": {}, "field_meta": {}, "treatments": [], "investigations": []}


def _normalise_ws(s: str) -> str:
    """Collapse runs of whitespace so a quote that differs only in spacing (PDF
    text extraction is inconsistent about it) still matches the document."""
    return " ".join(s.split())


def _field_meta(key: str, cell: dict, value, haystack: str | None) -> dict | None:
    """Confidence + provenance for one field, or None if neither is usable.

    Two mechanical checks, because the model's self-report is unreliable on both:

    1. The source must appear in the document — but only when we have the document
       as text. `haystack` is None for an upload containing images, where a quote
       may come from a page we can't read locally; verifying against the PDF text
       alone would strip every legitimate image quote.
    2. HIGH is downgraded to MEDIUM unless the value appears verbatim inside its
       own quote. Left to itself the model calls almost everything HIGH — a
       reformatted date or a boolean read off "No cardiac disease." is not a
       straight copy, and a reviewer needs to see that difference.
    """
    confidence = cell.get("confidence")
    if confidence not in CONFIDENCE_LEVELS:
        confidence = None

    source = cell.get("source")
    source = source.strip() if isinstance(source, str) else ""
    if source and haystack is not None and _normalise_ws(source).lower() not in haystack:
        logger.info("Dropping unverifiable case-sheet source for %s: %r", key, source[:80])
        source = ""

    if confidence == "HIGH" and source:
        needle = _normalise_ws(str(value)).lower()
        if needle and needle not in _normalise_ws(source).lower():
            confidence = "MEDIUM"

    if source and len(source) > _MAX_SOURCE_CHARS:
        source = source[:_MAX_SOURCE_CHARS].rstrip() + "…"

    if not confidence and not source:
        return None
    return {"confidence": confidence, "source": source or None}


def _clean_treatments(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    allowed = set(_DRUG_ROUTE_CODES)
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        routes = [
            str(r).strip().upper()
            for r in (item.get("drug_route") or [])
            if str(r).strip().upper() in allowed
        ]
        entry = {
            "treatment_details": (item.get("treatment_details") or "").strip() or None,
            "drug_route": list(dict.fromkeys(routes)),
            "surgery_icd_code": (item.get("surgery_icd_code") or "").strip().upper() or None,
            "injury_cause": (item.get("injury_cause") or "").strip() or None,
        }
        # An entry with nothing but an empty route list is noise.
        if entry["treatment_details"] or entry["surgery_icd_code"] or entry["injury_cause"]:
            out.append(entry)
    return out


def _clean_investigations(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("investigation_name") or "").strip().upper()
        # Drop anything that wouldn't resolve to a real dropdown option.
        if name not in _CATEGORY_OF:
            continue
        # The two enums are independent, so the model can file a valid test under
        # the wrong category (e.g. CRP as SEROLOGY_IMMUNOLOGY). The name is the
        # more specific signal — let it decide the category, otherwise the form's
        # cascading dropdown would show the value as a "(custom)" stand-in.
        out.append({
            "investigation_category": _CATEGORY_OF[name],
            "investigation_name": name,
            "investigation_description": (item.get("investigation_description") or "").strip() or None,
        })
    return out


def _is_image(name: str | None, ctype: str | None) -> bool:
    if (ctype or "").lower() in IMAGE_CONTENT_TYPES:
        return True
    ext = "." + (name or "").rsplit(".", 1)[-1].lower() if "." in (name or "") else ""
    return ext in {".jpg", ".jpeg", ".png", ".webp"}


def _image_mime(name: str | None, ctype: str | None) -> str:
    """The mime the data URL is labelled with — fall back to the extension when the
    browser sends something vague like application/octet-stream."""
    if (ctype or "").lower() in IMAGE_CONTENT_TYPES:
        return ctype.lower()
    ext = (name or "").rsplit(".", 1)[-1].lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")


def _image_url(image: tuple[bytes, str] | str) -> str:
    """The `url` handed to the model.

    A plain https string is passed straight through — OpenAI's servers fetch it
    themselves, which keeps our request small. Otherwise the bytes are inlined as
    a data URL, which is what local development uses because localhost is not
    reachable from OpenAI.
    """
    if isinstance(image, str):
        return image
    data_bytes, mime = image
    return f"data:{mime};base64,{base64.b64encode(data_bytes).decode()}"


def _is_unfetchable_url(e: Exception) -> bool:
    """Whether the model failed because it could not download the image link —
    timeout, DNS, TLS, 404. All surface as `invalid_image_url`."""
    return getattr(e, "code", None) == "invalid_image_url" or "invalid_image_url" in str(e)


def _call_page(client: OpenAI, prompt: str, image: tuple[bytes, str] | str | None) -> dict:
    content: list | str = prompt
    if image is not None:
        content = [
            {"type": "text", "text": prompt},
            # "high" is required: at "low" the model misreads names outright.
            {"type": "image_url",
             "image_url": {"url": _image_url(image), "detail": "high"}},
        ]
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_schema", "json_schema": _schema()},
        temperature=0,
    )
    if response.usage:
        logger.info(
            "Case sheet page extracted (%s): %s prompt tokens",
            "image" if image else "text", response.usage.prompt_tokens,
        )
    return json.loads(response.choices[0].message.content or "{}")


def _extract_page(
    client: OpenAI,
    text: str | None,
    image: tuple[bytes, str] | str | None,
    inline: tuple[bytes, str] | None = None,
) -> dict | None:
    """One page — either PDF text or a single photo. Returns the raw parsed object,
    or None if the call failed (one bad page shouldn't lose the others).

    `inline` is the same image as raw bytes, set only when `image` is a public URL.
    If OpenAI cannot download that link the page is retried with the bytes in the
    request body, so an unreachable or slow link costs bandwidth, not the page.
    """
    prompt = _PROMPT.format(
        text=text or "(no text layer — read the attached page image instead)",
        max_source=_MAX_SOURCE_CHARS,
    )
    try:
        return _call_page(client, prompt, image)
    except Exception as e:
        if inline is None or not _is_unfetchable_url(e):
            logger.error(f"Case sheet page extraction failed: {e}")
            return None
        logger.warning(
            "OpenAI could not fetch the page image link (%s) — retrying with the "
            "bytes inlined", e,
        )
    try:
        return _call_page(client, prompt, inline)
    except Exception as e:
        logger.error(f"Case sheet page extraction failed on inline retry: {e}")
        return None


_CONFIDENCE_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def _merge_pages(pages: list[dict], haystack: str | None) -> dict:
    """Fold per-page results into one. For a scalar field the best-supported page
    wins — higher confidence first, then earlier page — because a value stated
    plainly on page 2 beats one inferred on page 1. Repeatables are concatenated."""
    data: dict = {}
    field_meta: dict = {}
    best_rank: dict = {}

    for parsed in pages:
        for key in _SCALAR_FIELDS:
            cell = parsed.get(key)
            if not isinstance(cell, dict):
                continue
            value = cell.get("value")
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            meta = _field_meta(key, cell, value, haystack)
            rank = _CONFIDENCE_RANK.get((meta or {}).get("confidence"), 0)
            if key in data and rank <= best_rank.get(key, 0):
                continue
            data[key] = value
            best_rank[key] = rank
            if meta:
                field_meta[key] = meta
            else:
                field_meta.pop(key, None)

    treatments: list[dict] = []
    investigations: list[dict] = []
    summary = ""
    for parsed in pages:
        treatments.extend(_clean_treatments(parsed.get("treatments")))
        investigations.extend(_clean_investigations(parsed.get("investigations")))
        if not summary:
            summary = (parsed.get("summary") or "").strip()

    return {
        "summary": summary,
        "data": data,
        "field_meta": field_meta,
        "treatments": _dedupe(treatments, "treatment_details"),
        "investigations": _dedupe(investigations, "investigation_name"),
    }


def _dedupe(rows: list[dict], key: str) -> list[dict]:
    """Drop repeats across pages — the same test or treatment often appears on
    more than one page. Order preserved."""
    seen, out = set(), []
    for row in rows:
        marker = str(row.get(key) or "").strip().lower()
        if marker and marker in seen:
            continue
        if marker:
            seen.add(marker)
        out.append(row)
    return out


def extract_case_sheet(
    files: list[tuple[bytes, str | None, str | None]],
    image_urls: list[str] | None = None,
) -> dict:
    """Return {summary, data, field_meta, treatments, investigations}.

    Accepts a mixed list of PDFs and page photos. PDF text is read locally; each
    image is sent to the vision model. `data` is a flat map keyed by the form's own
    field keys, with nulls and blanks stripped — unchanged, because that map is what
    pre-fills the form. Falls back to an empty result on any failure: the user still
    gets a form they can fill in.
    """
    pdf_text_parts: list[str] = []
    # (what the model is given, the same image inlined as a fallback or None).
    images: list[tuple[tuple[bytes, str] | str, tuple[bytes, str] | None]] = []
    # When the caller supplies public links (one per image, in the same order as
    # the images appear in `files`), hand those to the model instead of inlining
    # the bytes. Same result either way — OpenAI downloads and tiles the image
    # identically, so the token cost is unchanged; only our request gets smaller.
    url_queue = list(image_urls or [])
    for data_bytes, name, ctype in files or []:
        if _is_image(name, ctype):
            inline = (data_bytes, _image_mime(name, ctype))
            url = url_queue.pop(0) if url_queue else None
            # The bytes are kept even when a link is used, so a link OpenAI cannot
            # download costs a retry rather than the whole page.
            images.append((url or inline, inline if url else None))
            continue
        text = extract_text(data_bytes, name, ctype)
        if text:
            pdf_text_parts.append(text)
        else:
            # Used to fail silently here — a scanned PDF has no text layer and we
            # cannot rasterise it without poppler. Say so.
            logger.warning(
                "No text could be read from case sheet %r (%s) — a scanned PDF needs "
                "to be uploaded as page images instead", name, ctype,
            )
    pdf_text = "\n\n".join(pdf_text_parts)

    if not pdf_text and not images:
        logger.warning("Case sheet upload produced neither text nor images")
        return _empty()
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not configured; skipping case sheet extraction")
        return _empty()

    # One call per page. See _PAGE_WORKERS for why images aren't batched.
    jobs: list[tuple] = []
    if pdf_text:
        jobs.append((pdf_text, None, None))
    jobs.extend((None, primary, inline) for primary, inline in images)

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    with ThreadPoolExecutor(max_workers=min(_PAGE_WORKERS, len(jobs))) as pool:
        pages = list(pool.map(lambda j: _extract_page(client, j[0], j[1], j[2]), jobs))
    pages = [p for p in pages if p]
    if not pages:
        return _empty()

    # Sources are verified against the document text — which only exists for PDFs.
    # With any image in the upload a quote may legitimately come from a page we have
    # no text for, so verification is skipped rather than silently dropping them all.
    haystack = _normalise_ws(pdf_text).lower() if pdf_text and not images else None

    return _merge_pages(pages, haystack)
