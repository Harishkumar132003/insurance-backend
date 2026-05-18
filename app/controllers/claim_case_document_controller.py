import os

from fastapi import HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from starlette.responses import Response
from sqlalchemy.orm import Session

from app.constants.claim_documents import CLAIM_DOCUMENT_TYPES
from app.models.claim_case import ClaimCase
from app.models.claim_case_document import ClaimCaseDocument
from app.models.claim_case_email import ClaimCaseEmail
from app.models.claim_case_email_attachment import ClaimCaseEmailAttachment
from app.utils.file_storage import save_document, delete_file, get_attachment_full_path, read_file


# Pre-auth approval email types that can supply Authorization Letter
# attachments to a raised claim.
_APPROVAL_EMAIL_TYPES = ("APPROVAL", "PARTIAL_APPROVAL", "ENHANCEMENT_APPROVAL")


def upload_documents(
    db: Session,
    claim_case_id,
    files: list[UploadFile],
    document_type: str | None = None,
) -> list[ClaimCaseDocument]:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )

    if document_type is not None and document_type not in CLAIM_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid document_type. Must be one of: {', '.join(CLAIM_DOCUMENT_TYPES)}",
        )

    documents = []
    for file in files:
        file_bytes = file.file.read()
        original_filename = file.filename or "unnamed_file"
        stored_filename, file_path = save_document(
            claim_case_id, file_bytes, original_filename
        )
        doc = ClaimCaseDocument(
            claim_case_id=claim_case_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_path=file_path,
            content_type=file.content_type,
            file_size=len(file_bytes),
            document_type=document_type,
        )
        db.add(doc)
        documents.append(doc)

    db.commit()
    for doc in documents:
        db.refresh(doc)
    return documents


def list_documents(db: Session, claim_case_id) -> list[ClaimCaseDocument]:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )
    return (
        db.query(ClaimCaseDocument)
        .filter(ClaimCaseDocument.claim_case_id == claim_case_id)
        .order_by(ClaimCaseDocument.created_at)
        .all()
    )


def delete_document(db: Session, claim_case_id, document_id: int) -> None:
    doc = (
        db.query(ClaimCaseDocument)
        .filter(
            ClaimCaseDocument.id == document_id,
            ClaimCaseDocument.claim_case_id == claim_case_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    delete_file(doc.file_path)
    db.delete(doc)
    db.commit()


def download_document(
    db: Session, claim_case_id, document_id: int
) -> FileResponse:
    doc = (
        db.query(ClaimCaseDocument)
        .filter(
            ClaimCaseDocument.id == document_id,
            ClaimCaseDocument.claim_case_id == claim_case_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    full_path = get_attachment_full_path(doc.file_path)
    if not os.path.exists(full_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk",
        )

    return FileResponse(
        path=full_path,
        filename=doc.original_filename,
        media_type=doc.content_type or "application/octet-stream",
    )


def attach_from_email(
    db: Session, claim_case_id, attachment_ids: list[int]
) -> list[ClaimCaseDocument]:
    if not attachment_ids:
        return []

    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )

    unique_ids = list({aid for aid in attachment_ids})
    rows = (
        db.query(ClaimCaseEmailAttachment)
        .join(ClaimCaseEmail, ClaimCaseEmail.id == ClaimCaseEmailAttachment.email_id)
        .filter(
            ClaimCaseEmailAttachment.id.in_(unique_ids),
            ClaimCaseEmailAttachment.claim_case_id == claim_case_id,
            ClaimCaseEmail.email_type.in_(_APPROVAL_EMAIL_TYPES),
        )
        .all()
    )
    if len(rows) != len(unique_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some attachment ids are invalid for this claim case",
        )

    created: list[ClaimCaseDocument] = []
    for att in rows:
        file_bytes = read_file(att.file_path)
        stored_filename, file_path = save_document(
            claim_case_id, file_bytes, att.original_filename
        )
        doc = ClaimCaseDocument(
            claim_case_id=claim_case_id,
            original_filename=att.original_filename,
            stored_filename=stored_filename,
            file_path=file_path,
            content_type=att.content_type,
            file_size=att.file_size,
            document_type="AUTHORIZATION_LETTERS",
        )
        db.add(doc)
        created.append(doc)

    db.commit()
    for doc in created:
        db.refresh(doc)
    return created


def view_document(
    db: Session, claim_case_id, document_id: int
) -> FileResponse:
    doc = (
        db.query(ClaimCaseDocument)
        .filter(
            ClaimCaseDocument.id == document_id,
            ClaimCaseDocument.claim_case_id == claim_case_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    full_path = get_attachment_full_path(doc.file_path)
    if not os.path.exists(full_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk",
        )

    return FileResponse(
        path=full_path,
        media_type=doc.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{doc.original_filename}"'},
    )
