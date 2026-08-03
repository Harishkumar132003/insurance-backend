"""Suggest ICD-10-PCS procedure codes for a pre-auth treatment row.

The pre-auth form's "ICD Code" is a free-text field with a Suggest ICD
button; this returns the three candidates the user picks from. Mirrors the
strict-JSON-schema pattern of summarize_policy_with_openai in openai_service.
"""
import json

from openai import OpenAIError
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.summary_prompt_template import SummaryPromptTemplate
from app.services.openai_service import client

# How many candidates we ask for and hand back.
SUGGESTION_COUNT = 3

# Prompts stored in the DB can be edited by an admin via /summary-prompts. This
# key is optional — when the row is absent we fall back to _DEFAULT_PROMPT.
PROMPT_KEY = "icd-suggestion"

# Cap on the rendered clinical context so a pathological paste can't blow up the
# request. Matches the ceiling used by document_extraction_service.
_MAX_CONTEXT_CHARS = 8000

ICD_SUGGESTION_SCHEMA = {
    "name": "icd_suggestions",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["suggestions"],
        "properties": {
            "suggestions": {
                "type": "array",
                "description": (
                    f"Exactly {SUGGESTION_COUNT} candidate codes, most likely first."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code", "description", "rationale"],
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "The 7-character ICD-10-PCS code, uppercase, no spaces.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Official procedure description for the code.",
                        },
                        "rationale": {
                            "type": "string",
                            "description": "One short sentence on why this code fits the context.",
                        },
                    },
                },
            },
        },
    },
}

_DEFAULT_PROMPT = f"""You are a certified Indian hospital medical coder assigning \
procedure codes for a cashless pre-authorisation request (Part C).

From the clinical context below, propose exactly {SUGGESTION_COUNT} candidate \
**ICD-10-PCS procedure codes** — the 7-character alphanumeric procedure codes \
(e.g. 0DTJ4ZZ), NOT ICD-10-CM diagnosis codes.

Rules:
- Order them most likely first.
- Base the code on the PROCEDURE described in the treatment details. Use the \
diagnosis, findings and history only to disambiguate approach, body part and device.
- Respect the documented approach (open vs percutaneous vs endoscopic) — if the \
approach is not stated, offer the plausible variants as the alternative candidates.
- Give the official procedure description for each code, and one short sentence \
saying which part of the context drove it.
- If the context describes no procedure at all, return the closest diagnostic or \
inspection procedures and say so in the rationale.

Clinical context (JSON):
{{clinical_context}}
"""


def _get_prompt_text(db: Session, key: str, default_prompt: str) -> str:
    """DB prompt override, falling back to the hardcoded default when no row
    exists. Same contract as workflow_executor's helper (kept local rather than
    importing a private symbol from that unrelated orchestrator)."""
    prompt = db.query(SummaryPromptTemplate).filter(SummaryPromptTemplate.key == key).first()
    if not prompt:
        return default_prompt
    return prompt.prompt_text


async def suggest_icd_codes(db: Session, context: dict) -> list[dict]:
    """Return up to SUGGESTION_COUNT {code, description, rationale} dicts."""
    rendered_context = json.dumps(context, ensure_ascii=False, default=str, indent=2)
    prompt = _get_prompt_text(db, PROMPT_KEY, _DEFAULT_PROMPT).replace(
        "{clinical_context}", rendered_context[:_MAX_CONTEXT_CHARS]
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": ICD_SUGGESTION_SCHEMA},
            temperature=0,
        )
        data = json.loads(response.choices[0].message.content or "{}")
    except OpenAIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI API error: {str(e)}",
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI returned invalid JSON: {str(e)}",
        )

    # Defensive clean-up: strict mode fixes the shape but not the content, so drop
    # entries with no code and cap the list even if the model over-delivers.
    out: list[dict] = []
    for item in (data.get("suggestions") or []):
        if not isinstance(item, dict):
            continue
        code = (item.get("code") or "").strip().upper()
        if not code:
            continue
        out.append({
            "code": code,
            "description": (item.get("description") or "").strip(),
            "rationale": (item.get("rationale") or "").strip() or None,
        })
    return out[:SUGGESTION_COUNT]
