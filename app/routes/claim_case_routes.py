from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.claim_case import ClaimCaseResponse, ClaimCaseDetailResponse, ClaimCaseStatusUpdate, ClaimCaseExtractedDataUpdate, ClaimListItem
from app.schemas.claim_case_document import ClaimCaseDocumentResponse
from app.schemas.claim_case_email import ClaimCaseEmailResponse, ClaimCaseEmailListResponse, PaginatedEmailListResponse
from app.controllers import claim_case_controller, claim_case_email_controller, claim_case_document_controller

router = APIRouter(prefix="/claim-cases", tags=["Claim Cases"])


@router.get("", response_model=list[ClaimListItem])
def get_all_claims(
    exclude_draft: bool = Query(default=False, description="Exclude claims with DRAFT status"),
    provider_id: UUID | None = Query(default=None, description="Filter by policy provider ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_controller.get_all_claims(
        db, current_user.hospital_id, exclude_draft=exclude_draft, provider_id=provider_id
    )


@router.get("/emails/all", response_model=PaginatedEmailListResponse)
def get_all_claim_case_emails(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.get_all_claim_case_emails(
        db, current_user.hospital_id, page=page, page_size=page_size
    )


@router.get("/{claim_case_id}", response_model=ClaimCaseDetailResponse)
def get_claim_case(
    claim_case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_controller.get_claim_case(db, claim_case_id)


@router.patch("/{claim_case_id}/status", response_model=ClaimCaseResponse)
def update_claim_case_status(
    claim_case_id: int,
    payload: ClaimCaseStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_controller.update_claim_case_status(
        db, claim_case_id, payload.status, payload.remarks, user_id=current_user.id
    )


@router.patch("/{claim_case_id}/emails/{email_id}/extracted-data", response_model=ClaimCaseResponse)
def update_extracted_data(
    claim_case_id: int,
    email_id: int,
    payload: ClaimCaseExtractedDataUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_controller.update_extracted_data(
        db, claim_case_id, email_id, payload, user_id=current_user.id
    )


@router.get("/{claim_case_id}/emails", response_model=list[ClaimCaseEmailListResponse])
def get_claim_case_emails(
    claim_case_id: int,
    direction: str | None = Query(default=None, description="Filter by SENT or RECEIVED"),
    email_type: str | None = Query(default=None, description="Filter by email type: QUERY_RAISED, QUERY_RESPONSE, APPROVAL, REJECTION, ADR"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.get_emails_for_claim_case(db, claim_case_id, direction, email_type)


@router.get("/{claim_case_id}/emails/all", response_model=list[ClaimCaseEmailResponse])
def get_all_emails_with_attachments(
    claim_case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.get_all_emails_with_attachments(db, claim_case_id)


@router.get("/{claim_case_id}/emails/{email_id}", response_model=ClaimCaseEmailResponse)
def get_claim_case_email_detail(
    claim_case_id: int,
    email_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.get_email_detail(db, claim_case_id, email_id)


@router.get("/{claim_case_id}/emails/{email_id}/attachments/{attachment_id}/download")
def download_email_attachment(
    claim_case_id: int,
    email_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.download_attachment(db, claim_case_id, email_id, attachment_id)


@router.get("/{claim_case_id}/emails/{email_id}/attachments/{attachment_id}/view")
def view_email_attachment(
    claim_case_id: int,
    email_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.view_attachment(db, claim_case_id, email_id, attachment_id)


# ── Document upload endpoints ──


@router.post("/{claim_case_id}/documents", response_model=list[ClaimCaseDocumentResponse], status_code=201)
async def upload_documents(
    claim_case_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_document_controller.upload_documents(db, claim_case_id, files)


@router.get("/{claim_case_id}/documents", response_model=list[ClaimCaseDocumentResponse])
def list_documents(
    claim_case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_document_controller.list_documents(db, claim_case_id)


@router.delete("/{claim_case_id}/documents/{document_id}", status_code=204)
def delete_document(
    claim_case_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    claim_case_document_controller.delete_document(db, claim_case_id, document_id)


@router.get("/{claim_case_id}/documents/{document_id}/download")
def download_document(
    claim_case_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_document_controller.download_document(db, claim_case_id, document_id)


@router.get("/{claim_case_id}/documents/{document_id}/view")
def view_document(
    claim_case_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_document_controller.view_document(db, claim_case_id, document_id)
