import os

from fastapi import HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from starlette.responses import Response
from sqlalchemy.orm import Session

from app.models.claim_case import ClaimCase
from app.models.claim_case_document import ClaimCaseDocument
from app.utils.file_storage import save_document, delete_file, get_attachment_full_path


def upload_documents(
    db: Session, claim_case_id, files: list[UploadFile]
) -> list[ClaimCaseDocument]:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
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
