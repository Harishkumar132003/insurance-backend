from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.claim_case import ClaimCase
from app.models.claim_case_email import ClaimCaseEmail
from app.models.claim_case_email_attachment import ClaimCaseEmailAttachment
from app.models.part_d_letter import PartDLetter
from app.schemas.part_d_letter import PartDLetterResponse, PART_D_FIELD_NAMES
from app.utils.file_storage import save_attachment


# Email types that represent an approval round and therefore can carry a Part-D.
_APPROVAL_EMAIL_TYPES = ("APPROVAL", "PARTIAL_APPROVAL", "ENHANCEMENT_APPROVAL")


def _get_claim_case(db: Session, claim_case_id, current_user=None) -> ClaimCase:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Claim case not found"
        )
    # Mirror get_claim_case: an INSURANCE_PROVIDER user may only touch claims
    # for their own provider.
    if (
        current_user is not None
        and getattr(current_user, "role", None) == "INSURANCE_PROVIDER"
        and claim_case.policy_provider_id != current_user.policy_provider_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to access this claim case",
        )
    return claim_case


def _find_approval_email(
    db: Session, claim_case, email_id: int | None
) -> ClaimCaseEmail | None:
    """Like `_resolve_approval_email` but tolerant when no approval exists yet.

    - With `email_id`: validates it belongs to this claim and is an approval
      email; raises 404/400 on mismatch (caller-supplied id must be valid).
    - Without `email_id`: returns the most recent approval email — UNLESS the
      case is currently awaiting a fresh provider decision (a new round after
      an enhancement / ADR), in which case it returns `None` so callers operate
      on a NEW draft Part-D instead of reusing the previous round's letter.
    """
    if email_id is not None:
        email = (
            db.query(ClaimCaseEmail)
            .filter(
                ClaimCaseEmail.id == email_id,
                ClaimCaseEmail.claim_case_id == claim_case.id,
            )
            .first()
        )
        if not email:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email not found for this claim case",
            )
        if email.email_type not in _APPROVAL_EMAIL_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Email {email_id} is not an approval email "
                    f"(email_type={email.email_type})"
                ),
            )
        return email

    # Fresh round pending → don't reuse a prior approval's bound Part-D.
    from app.controllers.claim_case_controller import AWAITING_PROVIDER_STATUSES
    if claim_case.status in AWAITING_PROVIDER_STATUSES:
        return None

    return (
        db.query(ClaimCaseEmail)
        .filter(
            ClaimCaseEmail.claim_case_id == claim_case.id,
            ClaimCaseEmail.email_type.in_(_APPROVAL_EMAIL_TYPES),
        )
        .order_by(ClaimCaseEmail.created_at.desc())
        .first()
    )


def _to_response(part_d: PartDLetter) -> PartDLetterResponse:
    resp = PartDLetterResponse.model_validate(part_d)
    resp.is_persisted = True
    return resp


def _stub_response(
    claim_case: ClaimCase, email: ClaimCaseEmail | None
) -> PartDLetterResponse:
    """A not-yet-persisted Part-D prefilled from the claim. The modal renders
    from this on first open; nothing is written until a PUT. When `email` is
    None (draft mode pre-approval), `claim_case_email_id` is omitted."""
    return PartDLetterResponse(
        claim_case_id=claim_case.id,
        claim_case_email_id=email.id if email else None,
        approved_amount=(
            float(claim_case.approved_amount)
            if claim_case.approved_amount is not None else None
        ),
        claim_number=claim_case.claim_number,
        is_persisted=False,
    )


def _find_existing_part_d(
    db: Session, claim_case_id, email: ClaimCaseEmail | None
) -> PartDLetter | None:
    """Existing Part-D row for the resolved scope: bound to the approval email
    if one is given, else the case's draft (email_id IS NULL)."""
    if email is not None:
        return (
            db.query(PartDLetter)
            .filter(PartDLetter.claim_case_email_id == email.id)
            .first()
        )
    return (
        db.query(PartDLetter)
        .filter(
            PartDLetter.claim_case_id == claim_case_id,
            PartDLetter.claim_case_email_id.is_(None),
        )
        .first()
    )


def get_part_d(
    db: Session, claim_case_id, email_id: int | None = None, current_user=None
) -> PartDLetterResponse:
    claim_case = _get_claim_case(db, claim_case_id, current_user)
    email = _find_approval_email(db, claim_case, email_id)
    part_d = _find_existing_part_d(db, claim_case_id, email)
    if part_d:
        return _to_response(part_d)
    return _stub_response(claim_case, email)


def upsert_part_d(
    db: Session,
    claim_case_id,
    fields: dict,
    email_id: int | None = None,
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
    attachment_content_type: str | None = None,
    current_user=None,
) -> PartDLetterResponse:
    """Create or update the Part-D for this claim_case.

    - Post-approval: bound to the resolved approval email (one Part-D per
      approval round).
    - Pre-approval (no approval email yet): persisted as a draft with
      `claim_case_email_id = NULL`. When the provider later approves via
      `process_by_provider`, the draft is linked to the new approval email.

    `fields` is a dict of {field_name: value} — only keys present are applied
    (partial update). A file attachment can only be persisted when an approval
    email exists (we need an email to bind the `ClaimCaseEmailAttachment`).
    """
    claim_case = _get_claim_case(db, claim_case_id, current_user)
    email = _find_approval_email(db, claim_case, email_id)

    part_d = _find_existing_part_d(db, claim_case_id, email)
    if not part_d:
        part_d = PartDLetter(
            claim_case_id=claim_case.id,
            claim_case_email_id=email.id if email else None,
            # Sensible defaults from the claim for the two header fields, so a
            # PUT that omits them still produces a complete-looking letter.
            approved_amount=claim_case.approved_amount,
            claim_number=claim_case.claim_number,
        )
        db.add(part_d)

    for name in PART_D_FIELD_NAMES:
        if name in fields:
            setattr(part_d, name, fields[name])

    if attachment_bytes and attachment_filename:
        if email is None:
            # Draft Part-D has no email to bind an attachment to. We silently
            # drop the file at this stage — the provider attaches the printed
            # PDF manually inside the Approve modal, which uses a different
            # code path (process_by_provider) to persist the attachment.
            pass
        else:
            db.flush()  # need email + part_d ids
            stored_filename, file_path = save_attachment(
                claim_case.id, attachment_bytes, attachment_filename
            )
            att = ClaimCaseEmailAttachment(
                email_id=email.id,
                claim_case_id=claim_case.id,
                original_filename=attachment_filename,
                stored_filename=stored_filename,
                file_path=file_path,
                content_type=attachment_content_type,
                file_size=len(attachment_bytes),
            )
            db.add(att)
            db.flush()
            part_d.attachment_id = att.id

    db.commit()
    db.refresh(part_d)
    return _to_response(part_d)
