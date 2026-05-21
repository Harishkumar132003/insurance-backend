"""Extract room/ICU/OT charges from an uploaded MOU document.

Provider identity (name, TPA fields, email) is typed by the admin — only the
charge schedule is parsed here. Returns the charges shape the onboarding form
renders as editable rows:
    {"room_type": [{"room": "NICU", "per_day_rent": 15000}], "icu": 3000, "ot_charge": 3000}
"""
import io
import json
import logging

from openai import OpenAI
from PyPDF2 import PdfReader

from app.core.config import settings

logger = logging.getLogger(__name__)


_CHARGES_SCHEMA = {
    "name": "mou_charges",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["room_type", "icu", "ot_charge"],
        "properties": {
            "room_type": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["room", "per_day_rent"],
                    "properties": {
                        "room": {"type": "string"},
                        "per_day_rent": {"type": ["number", "null"]},
                    },
                },
            },
            "icu": {"type": ["number", "null"]},
            "ot_charge": {"type": ["number", "null"]},
        },
    },
}


_PROMPT = """You are reading a hospital–insurer MOU (Memorandum of Understanding).

Extract the agreed tariff. Return ONE JSON object:
- `room_type`: a list of {{room, per_day_rent}} for each named room/ward category
  (e.g. "General Ward", "Private Single Room", "NICU", "Emergency Room"). Use the
  per-day rent in plain rupees as a number (15000, not "₹15,000"). Use null if a
  category is listed without a rate.
- `icu`: the ICU per-day charge as a number, or null if not stated.
- `ot_charge`: the operation-theatre charge as a number, or null if not stated.

Only include rooms actually present in the document. Do not invent categories.

MOU text:
{text}
"""


def _extract_pdf_text(file_bytes: bytes, file_name: str | None, content_type: str | None,
                      max_chars: int = 12000) -> str:
    is_pdf = (
        (content_type or "").lower() == "application/pdf"
        or ((file_name or "").lower().endswith(".pdf"))
    )
    try:
        if is_pdf:
            reader = PdfReader(io.BytesIO(file_bytes))
            parts = [p.extract_text() for p in reader.pages]
            text = "\n".join(t for t in parts if t).strip()
        else:
            text = file_bytes.decode("utf-8", errors="replace").strip()
    except Exception:
        text = ""
    return text[:max_chars]


def _empty() -> dict:
    return {"room_type": [], "icu": None, "ot_charge": None}


def extract_mou_data(file_bytes: bytes, file_name: str | None, content_type: str | None) -> dict:
    """Return the charges dict. Falls back to an empty editable shape on any
    failure so the admin can still fill it in manually."""
    text = _extract_pdf_text(file_bytes, file_name, content_type)
    if not text:
        return _empty()
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not configured; skipping MOU extraction")
        return _empty()

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": _PROMPT.format(text=text)}],
            response_format={"type": "json_schema", "json_schema": _CHARGES_SCHEMA},
            temperature=0,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        rooms = data.get("room_type") or []
        if not isinstance(rooms, list):
            rooms = []
        return {
            "room_type": [
                {"room": str(r.get("room", "")).strip(), "per_day_rent": r.get("per_day_rent")}
                for r in rooms
                if isinstance(r, dict) and str(r.get("room", "")).strip()
            ],
            "icu": data.get("icu"),
            "ot_charge": data.get("ot_charge"),
        }
    except Exception as e:
        logger.error(f"MOU extraction failed: {e}")
        return _empty()
