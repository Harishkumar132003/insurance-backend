from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_insurance_provider
from app.models.user import User
from app.schemas.claim_case import (
    ClaimCaseResponse,
    ClaimCaseDetailResponse,
    ClaimCaseStatusUpdate,
    ClaimCaseExtractedDataUpdate,
    ClaimCaseSubmissionsResponse,
    ClaimListItem,
    PaginatedProviderQueueResponse,
)
from app.schemas.claim_case_document import ClaimCaseDocumentResponse
from app.schemas.claim_case_email import ClaimCaseEmailResponse, ClaimCaseEmailListResponse, PaginatedEmailListResponse, ClaimCaseEmailValidateRequest
from app.schemas.part_d_letter import PartDLetterResponse, PART_D_FIELD_NAMES
from app.controllers import (
    claim_case_controller,
    claim_case_email_controller,
    claim_case_document_controller,
    part_d_letter_controller,
)

router = APIRouter(prefix="/claim-cases", tags=["Claim Cases"])


@router.get("", response_model=list[ClaimListItem])
def get_all_claims(
    exclude_draft: bool = Query(default=False, description="Exclude claims with DRAFT status"),
    provider_id: UUID | None = Query(default=None, description="Filter by policy provider ID"),
    q: str | None = Query(default=None, description="Search by UHID or patient name (case-insensitive substring match)"),
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
        exclude_draft=exclude_draft or current_user.role == "INSURANCE_PROVIDER",
        provider_id=provider_id,
        policy_provider_id=policy_provider_id,
        q=q,
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
async def provider_action(
    claim_case_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_insurance_provider),
):
    """Accepts JSON or multipart/form-data. JSON is the simple path; multipart
    is required when attaching a file (approval letter / supporting doc)."""
    content_type = request.headers.get("content-type", "")

    file_bytes: bytes | None = None
    file_name: str | None = None
    file_content_type: str | None = None

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        new_status = form.get("status")
        approved_amount_raw = form.get("approved_amount")
        claim_number = form.get("claim_number")
        remarks = form.get("remarks")
        query_details = form.get("query_details")
        documents_requested = form.get("documents_requested")
        documents_list = form.getlist("documents_list") or None
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read") and getattr(upload, "filename", None):
            file_bytes = await upload.read()
            file_name = upload.filename
            file_content_type = upload.content_type
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Body must be valid JSON or multipart/form-data",
            )
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON body must be an object",
            )
        new_status = body.get("status")
        approved_amount_raw = body.get("approved_amount")
        claim_number = body.get("claim_number")
        remarks = body.get("remarks")
        query_details = body.get("query_details")
        documents_requested = body.get("documents_requested")
        documents_list = body.get("documents_list")

    if not new_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status is required",
        )

    approved_amount = None
    if approved_amount_raw not in (None, ""):
        try:
            approved_amount = float(approved_amount_raw)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="approved_amount must be a number",
            )

    return claim_case_email_controller.process_by_provider(
        db,
        claim_case_id,
        current_user,
        new_status=new_status,
        approved_amount=approved_amount,
        claim_number=claim_number,
        remarks=remarks,
        query_details=query_details,
        documents_requested=documents_requested,
        documents_list=documents_list,
        attachment_bytes=file_bytes,
        attachment_filename=file_name,
        attachment_content_type=file_content_type,
    )


@router.get("/{claim_case_id}/part-d", response_model=PartDLetterResponse)
def get_part_d(
    claim_case_id: UUID,
    email_id: int | None = Query(default=None, description="Approval email id; defaults to the latest approval"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Prefill source for the Part-D modal. Returns the saved letter for the
    approval round, or a stub (approved_amount + claim_number from the claim,
    is_persisted=false) when nothing has been saved yet."""
    return part_d_letter_controller.get_part_d(db, claim_case_id, email_id, current_user)


@router.put("/{claim_case_id}/part-d", response_model=PartDLetterResponse)
async def put_part_d(
    claim_case_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_insurance_provider),
):
    """Save the Part-D field values for an approval round. Accepts JSON (just
    the field values) or multipart/form-data (field values + optional `file`
    = the rendered PDF + optional `email_id`). Upserts; partial updates OK."""
    content_type = request.headers.get("content-type", "")

    file_bytes: bytes | None = None
    file_name: str | None = None
    file_content_type: str | None = None
    email_id: int | None = None
    fields: dict = {}

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        for name in PART_D_FIELD_NAMES:
            if name in form:
                fields[name] = form.get(name)
        raw_email_id = form.get("email_id")
        if raw_email_id not in (None, ""):
            try:
                email_id = int(raw_email_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email_id must be an integer")
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read") and getattr(upload, "filename", None):
            file_bytes = await upload.read()
            file_name = upload.filename
            file_content_type = upload.content_type
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Body must be valid JSON or multipart/form-data",
            )
        if not isinstance(body, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON body must be an object")
        for name in PART_D_FIELD_NAMES:
            if name in body:
                fields[name] = body[name]
        if "email_id" in body and body["email_id"] is not None:
            try:
                email_id = int(body["email_id"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email_id must be an integer")

    # Coerce approved_amount to float if it came through as a form string.
    if "approved_amount" in fields and fields["approved_amount"] not in (None, ""):
        try:
            fields["approved_amount"] = float(fields["approved_amount"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="approved_amount must be a number")
    elif fields.get("approved_amount") == "":
        fields["approved_amount"] = None

    return part_d_letter_controller.upsert_part_d(
        db,
        claim_case_id,
        fields,
        email_id=email_id,
        attachment_bytes=file_bytes,
        attachment_filename=file_name,
        attachment_content_type=file_content_type,
        current_user=current_user,
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


@router.get("/{claim_case_id}/submissions", response_model=ClaimCaseSubmissionsResponse)
def get_submissions_and_responses(
    claim_case_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Reuse the access guard on the detail endpoint (raises 403 for cross-tenant
    # INSURANCE_PROVIDER access).
    claim_case_controller.get_claim_case(db, claim_case_id, current_user=current_user)
    return claim_case_email_controller.get_submissions_and_responses(db, claim_case_id)


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
    email_type: str | None = Query(default=None, description="Filter by email type: SUBMITTED, ENHANCE_SUBMITTED, RECONSIDER, ADR_SUBMITTED, APPROVAL, PARTIAL_APPROVAL, DENIAL, ENHANCEMENT_APPROVAL, ENHANCEMENT_DENIAL, ADR_NMI"),
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
