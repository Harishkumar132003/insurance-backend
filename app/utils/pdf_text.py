"""Extract plain text from an uploaded document for the AI extractors.

Lifted from the private copies in mou_extraction_service / workflow_executor so
new extractors have one obvious home. Those two are deliberately left as they
are — this is not a refactor of working code.
"""
import io

from PyPDF2 import PdfReader

# Roughly the useful context window for the extraction prompts. Long documents
# are truncated, so anything past this is silently ignored.
DEFAULT_MAX_CHARS = 12000


def extract_text(
    file_bytes: bytes,
    file_name: str | None,
    content_type: str | None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Best-effort text for a PDF (or any UTF-8-decodable file).

    Returns "" rather than raising — callers treat empty text as "nothing to
    extract" and fall back to an empty result the user can fill in by hand.
    """
    is_pdf = (
        (content_type or "").lower() == "application/pdf"
        or (file_name or "").lower().endswith(".pdf")
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
