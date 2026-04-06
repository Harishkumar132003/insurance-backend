import os
import uuid

from app.core.config import settings

UPLOAD_BASE_DIR = getattr(settings, "UPLOAD_DIR", "uploads")


def save_attachment(claim_case_id: int, file_bytes: bytes, original_filename: str) -> tuple[str, str]:
    """Save file to disk. Returns (stored_filename, relative_file_path)."""
    dir_path = os.path.join(UPLOAD_BASE_DIR, "claim_cases", str(claim_case_id), "attachments")
    os.makedirs(dir_path, exist_ok=True)

    ext = os.path.splitext(original_filename)[1]
    stored_filename = f"{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(dir_path, stored_filename)

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    return stored_filename, file_path


def get_attachment_full_path(file_path: str) -> str:
    """Return absolute path for serving a file."""
    return os.path.abspath(file_path)
