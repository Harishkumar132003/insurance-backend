from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_insurance_provider
from app.models.user import User
from app.schemas.claim_case import (
    ClaimCaseResponse,
    ClaimCaseDetailResponse,
    ClaimCaseStatusUpdate,
    ClaimCaseExtractedDataUpdate,
    ClaimListItem,
    PaginatedProviderQueueResponse,
    ProviderActionRequest,
)
from app.schemas.claim_case_document import ClaimCaseDocumentResponse
from app.schemas.claim_case_email import ClaimCaseEmailResponse, ClaimCaseEmailListResponse, PaginatedEmailListResponse, ClaimCaseEmailValidateRequest
from app.controllers import claim_case_controller, claim_case_email_controller, claim_case_document_controller

router = APIRouter(prefix="/claim-cases", tags=["Claim Cases"])


@router.get("", response_model=list[ClaimListItem])
def get_all_claims(
    exclude_draft: bool = Query(default=False, description="Exclude claims with DRAFT status"),
    provider_id: UUID | None = Query(default=None, description="Filter by policy provider ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    policy_provider_id = (
        current_user.policy_provider_id
        if current_user.role == "INSURANCE_PROVIDER"
        else None
    )
    return claim_case_controller.get_all_claims(
        db,
        current_user.hospital_id,
        exclude_draft=exclude_draft,
        provider_id=provider_id,
        policy_provider_id=policy_provider_id,
    )


@router.get("/provider-queue", response_model=PaginatedProviderQueueResponse)
def get_provider_queue(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_insurance_provider),
):
    if not current_user.policy_provider_id:
        from fastapi import HTTPException, status as _status
        raise HTTPException(
            status_code=_status.HTTP_400_BAD_REQUEST,
            detail="User is not linked to a policy provider",
        )
    return claim_case_email_controller.get_provider_queue(
        db, current_user.policy_provider_id, page=page, page_size=page_size
    )


@router.patch("/{claim_case_id}/provider-action", response_model=ClaimCaseResponse)
def provider_action(
    claim_case_id: UUID,
    payload: ProviderActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_insurance_provider),
):
    return claim_case_email_controller.process_by_provider(
        db,
        claim_case_id,
        current_user,
        new_status=payload.status,
        approved_amount=payload.approved_amount,
        claim_number=payload.claim_number,
        remarks=payload.remarks,
        query_details=payload.query_details,
        documents_requested=payload.documents_requested,
    )


@router.get("/emails/all", response_model=PaginatedEmailListResponse)
def get_all_claim_case_emails(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    claim_case_id: UUID | None = Query(default=None, description="Filter by claim case ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    policy_provider_id = (
        current_user.policy_provider_id
        if current_user.role == "INSURANCE_PROVIDER"
        else None
    )
    return claim_case_email_controller.get_all_claim_case_emails(
        db,
        current_user.hospital_id,
        page=page,
        page_size=page_size,
        claim_case_id=claim_case_id,
        policy_provider_id=policy_provider_id,
    )


@router.get("/{claim_case_id}", response_model=ClaimCaseDetailResponse)
def get_claim_case(
    claim_case_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_controller.get_claim_case(db, claim_case_id, current_user=current_user)


@router.patch("/{claim_case_id}/status", response_model=ClaimCaseResponse)
def update_claim_case_status(
    claim_case_id: UUID,
    payload: ClaimCaseStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_controller.update_claim_case_status(
        db, claim_case_id, payload.status, payload.remarks, user_id=current_user.id
    )


@router.patch("/{claim_case_id}/emails/{email_id}/extracted-data", response_model=ClaimCaseResponse)
def update_extracted_data(
    claim_case_id: UUID,
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
    claim_case_id: UUID,
    direction: str | None = Query(default=None, description="Filter by SENT or RECEIVED"),
    email_type: str | None = Query(default=None, description="Filter by email type: SUBMITTED, ENHANCE_SUBMITTED, RECONSIDER, ADR_SUBMITTED, APPROVAL, PARTIAL_APPROVAL, DENIAL, ADR_NMI"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.get_emails_for_claim_case(db, claim_case_id, direction, email_type)


@router.get("/{claim_case_id}/emails/all", response_model=list[ClaimCaseEmailResponse])
def get_all_emails_with_attachments(
    claim_case_id: UUID,
    is_read: bool | None = Query(default=None, description="Filter by read status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.get_all_emails_with_attachments(db, claim_case_id, is_read=is_read)


@router.get("/{claim_case_id}/emails/{email_id}", response_model=ClaimCaseEmailResponse)
def get_claim_case_email_detail(
    claim_case_id: UUID,
    email_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.get_email_detail(db, claim_case_id, email_id)


@router.patch("/{claim_case_id}/emails/{email_id}/read", response_model=ClaimCaseEmailResponse)
def mark_email_as_read(
    claim_case_id: UUID,
    email_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.mark_email_as_read(
        db, claim_case_id, email_id, current_user=current_user
    )


@router.patch("/{claim_case_id}/emails/{email_id}/validate", response_model=ClaimCaseEmailResponse)
def validate_email_suggestion(
    claim_case_id: UUID,
    email_id: int,
    payload: ClaimCaseEmailValidateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.validate_email_suggestion(
        db, claim_case_id, email_id, payload.validation_status, current_user.id, payload.remarks
    )


@router.get("/{claim_case_id}/emails/{email_id}/attachments/{attachment_id}/download")
def download_email_attachment(
    claim_case_id: UUID,
    email_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.download_attachment(db, claim_case_id, email_id, attachment_id)


@router.get("/{claim_case_id}/emails/{email_id}/attachments/{attachment_id}/view")
def view_email_attachment(
    claim_case_id: UUID,
    email_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_email_controller.view_attachment(db, claim_case_id, email_id, attachment_id)


# ── Document upload endpoints ──


@router.post("/{claim_case_id}/documents", response_model=list[ClaimCaseDocumentResponse], status_code=201)
async def upload_documents(
    claim_case_id: UUID,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_document_controller.upload_documents(db, claim_case_id, files)


@router.get("/{claim_case_id}/documents", response_model=list[ClaimCaseDocumentResponse])
def list_documents(
    claim_case_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_document_controller.list_documents(db, claim_case_id)


@router.delete("/{claim_case_id}/documents/{document_id}", status_code=204)
def delete_document(
    claim_case_id: UUID,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    claim_case_document_controller.delete_document(db, claim_case_id, document_id)


@router.get("/{claim_case_id}/documents/{document_id}/download")
def download_document(
    claim_case_id: UUID,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_document_controller.download_document(db, claim_case_id, document_id)


@router.get("/{claim_case_id}/documents/{document_id}/view")
def view_document(
    claim_case_id: UUID,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return claim_case_document_controller.view_document(db, claim_case_id, document_id)
