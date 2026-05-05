"""AI helper that turns free-form ADR text into a structured list of
document names. Used by the in-app provider-action flow and the email
reader so the frontend can render checkboxes / discrete items."""
import json
import logging

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


_PROMPT = """
You are an expert in Indian health insurance claim processing.

From the text below, extract the discrete document names a hospital is
being asked to provide. Trim each entry. Merge near-duplicates. Use the
canonical document name (e.g. "Discharge Summary", "Final Bill",
"Investigation Reports", "Indoor Case Papers").

Return STRICT JSON only:
{{ "documents": ["...", "..."] }}

If no documents are being requested, return:
{{ "documents": [] }}

Text:
{text}
"""


def extract_documents(text: str | None) -> list[str] | None:
    """Return a list of document names extracted from `text`.

    Returns `None` when extraction is unavailable (no API key, OpenAI error)
    so callers can persist the prose as-is and not block the user action.
    Returns `[]` when the model says no documents are requested.
    """
    if not text or not text.strip():
        return []
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not configured; skipping document extraction")
        return None

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": _PROMPT.format(text=text[:8000])}],
            temperature=0,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        data = json.loads(content)
        docs = data.get("documents") or []
        if not isinstance(docs, list):
            return []
        return [str(d).strip() for d in docs if str(d).strip()]
    except Exception as e:
        logger.error(f"Document extraction failed: {e}")
        return None
