"""Case sheet extraction: run the AI read, keep the document and the audit trail.

Two-phase, mirroring the settlement flow: the row is created at extract time —
before any claim case exists — and `claim_case_id` is filled in when the form
built from it is first saved.
"""
import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.case_sheet_extraction import CaseSheetExtraction
from app.services.case_sheet_extraction_service import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_EXTENSIONS,
    MAX_FILES,
    MAX_FILE_BYTES,
    _is_image,
    extract_case_sheet,
)
from app.utils.file_storage import save_case_sheet
from app.utils.signed_links import sign

logger = logging.getLogger(__name__)


def _validate(files: list[tuple[bytes, str | None, str | None]]) -> None:
    """Reject before anything is written to disk or sent to the model.

    The first upload validation in this codebase — images are base64-encoded into
    the AI request, so an unbounded upload is both a very large request and a
    needlessly expensive call.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No case sheet uploaded"
        )
    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload at most {MAX_FILES} files per case sheet (got {len(files)})",
        )
    for data_bytes, name, ctype in files:
        label = name or "file"
        if not data_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"{label} is empty"
            )
        if len(data_bytes) > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{label} is {len(data_bytes) / (1024 * 1024):.1f} MB — the limit is "
                       f"{MAX_FILE_BYTES // (1024 * 1024)} MB per file",
            )
        # Check the declared type AND the extension: `accept` in the browser is
        # trivially bypassed, and some clients send application/octet-stream.
        ext = "." + label.rsplit(".", 1)[-1].lower() if "." in label else ""
        if (ctype or "").lower() not in ALLOWED_CONTENT_TYPES and ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{label} must be a PDF or an image (JPEG, PNG, WebP)",
            )


def extract_and_store(
    db: Session,
    hospital_id,
    user_id,
    files: list[tuple[bytes, str | None, str | None]],
) -> dict:
    """Store the case sheet pages, extract them together, and keep both.

    Files are saved even when the extraction comes back empty — the documents are
    worth keeping regardless, and the user can still fill the form by hand.
    """
    _validate(files)

    # Files are stored and the row created and COMMITTED before extraction. The id
    # is needed to mint the public image link, and a flush alone is not enough: the
    # request that serves that link opens its own session, and under READ COMMITTED
    # an uncommitted row does not exist yet — OpenAI would be handed a link to a
    # 404. Committing here also releases the transaction for the duration of the
    # AI calls instead of holding it open for the whole extraction.
    stored: list[dict] = []
    for data_bytes, name, ctype in files:
        stored_filename, file_path = save_case_sheet(
            hospital_id, data_bytes, name or "case_sheet.pdf"
        )
        stored.append({
            "original_filename": name,
            "stored_filename": stored_filename,
            "file_path": file_path,
            "content_type": ctype,
            "size": len(data_bytes),
        })

    first = stored[0]
    row = CaseSheetExtraction(
        hospital_id=hospital_id,
        created_by=user_id,
        files=stored,
        # The four scalar columns mirror page 1, so the single-file read paths and
        # the rows written before multi-file support keep working unchanged.
        original_filename=first["original_filename"],
        stored_filename=first["stored_filename"],
        file_path=first["file_path"],
        content_type=first["content_type"],
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    result = extract_case_sheet(files, image_urls=_public_image_urls(row, files))

    row.summary = result.get("summary") or None
    row.extracted = result.get("data") or {}
    row.field_meta = result.get("field_meta") or {}
    row.treatments = result.get("treatments") or []
    row.investigations = result.get("investigations") or []
    db.commit()
    db.refresh(row)

    return {**result, "case_sheet_id": row.id, "files": _file_list(row)}


def _public_image_urls(
    row: CaseSheetExtraction, files: list[tuple[bytes, str | None, str | None]]
) -> list[str]:
    """Signed, short-lived links to each image page, in the order the images
    appear in `files`.

    Empty unless PUBLIC_BASE_URL is configured — OpenAI fetches these itself, so
    they have to be reachable from the public internet. Locally that is never
    true, and the caller falls back to inlining the bytes.
    """
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    if not base:
        return []
    urls = []
    for index, (_, name, ctype) in enumerate(files):
        if not _is_image(name, ctype):
            continue
        expires_at, signature = sign(str(row.id), index)
        urls.append(
            f"{base}/api/v1/public/case-sheets/{row.id}/files/{index}"
            f"?exp={expires_at}&sig={signature}"
        )
    return urls


def get_file_ref_unscoped(db: Session, case_sheet_id, index: int) -> dict:
    """A page WITHOUT a tenant check — only for the signed public link, where the
    signature is what authorises the read. Everything else must use get_file_ref.
    """
    row = (
        db.query(CaseSheetExtraction)
        .filter(CaseSheetExtraction.id == case_sheet_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    entries = row.files if isinstance(row.files, list) and row.files else []
    if index < 0 or index >= len(entries):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return entries[index]


def _file_list(row: CaseSheetExtraction) -> list[dict]:
    """What the client needs to show and open each page. Falls back to the scalar
    columns for rows written before `files` existed."""
    entries = row.files if isinstance(row.files, list) and row.files else None
    if entries is None:
        if not row.file_path:
            return []
        entries = [{
            "original_filename": row.original_filename,
            "content_type": row.content_type,
        }]
    return [
        {
            "index": i,
            "original_filename": e.get("original_filename"),
            "content_type": e.get("content_type"),
        }
        for i, e in enumerate(entries)
    ]


def get_file_ref(db: Session, hospital_id, case_sheet_id, index: int) -> dict:
    """One stored page, tenant-scoped."""
    row = get_for_file(db, hospital_id, case_sheet_id)
    entries = row.files if isinstance(row.files, list) and row.files else [{
        "original_filename": row.original_filename,
        "file_path": row.file_path,
        "content_type": row.content_type,
    }]
    if index < 0 or index >= len(entries):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Case sheet page not found"
        )
    return entries[index]


def get_for_file(db: Session, hospital_id, case_sheet_id) -> CaseSheetExtraction:
    """Tenant-scoped fetch for serving the stored PDF back."""
    row = (
        db.query(CaseSheetExtraction)
        .filter(
            CaseSheetExtraction.id == case_sheet_id,
            CaseSheetExtraction.hospital_id == hospital_id,
        )
        .first()
    )
    if not row or not row.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Case sheet not found"
        )
    return row


def get_for_claim_case(db: Session, hospital_id, claim_case_id) -> dict | None:
    """The extraction behind a saved case, for re-showing confidence + provenance
    when the form is reopened. Returns None when the case wasn't built from a
    case sheet.

    `extracted` comes back too so the caller can tell which values are still the
    AI's: a score next to a figure the user has since corrected would be a lie.
    """
    row = (
        db.query(CaseSheetExtraction)
        .filter(
            CaseSheetExtraction.claim_case_id == claim_case_id,
            CaseSheetExtraction.hospital_id == hospital_id,
        )
        .order_by(CaseSheetExtraction.created_at.desc())
        .first()
    )
    if not row:
        return None
    return {
        "case_sheet_id": row.id,
        "original_filename": row.original_filename,
        "created_at": row.created_at,
        "extracted": row.extracted or {},
        "field_meta": row.field_meta or {},
        "files": _file_list(row),
    }


def link_to_claim_case(db: Session, hospital_id, case_sheet_id, claim_case_id) -> None:
    """Attach an extraction to the case its form created. Best-effort: a bad or
    foreign id is ignored rather than failing the save, since the form itself has
    already been submitted successfully by this point.

    Does not commit — the caller owns the transaction that creates the case.
    """
    if not case_sheet_id:
        return
    row = (
        db.query(CaseSheetExtraction)
        .filter(
            CaseSheetExtraction.id == case_sheet_id,
            CaseSheetExtraction.hospital_id == hospital_id,
        )
        .first()
    )
    if not row:
        logger.warning("Ignoring unknown case_sheet_id %s for hospital %s", case_sheet_id, hospital_id)
        return
    row.claim_case_id = claim_case_id
