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


def _resolve_approval_email(
    db: Session, claim_case_id, email_id: int | None
) -> ClaimCaseEmail:
    """Return the APPROVAL / PARTIAL_APPROVAL email a Part-D belongs to.

    If `email_id` is given, validate it belongs to this claim and is an
    approval email. Otherwise return the most recent approval email. 404 if
    the claim has no approval email yet — you can't write an authorization
    letter for an unapproved claim.
    """
    if email_id is not None:
        email = (
            db.query(ClaimCaseEmail)
            .filter(
                ClaimCaseEmail.id == email_id,
                ClaimCaseEmail.claim_case_id == claim_case_id,
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

    email = (
        db.query(ClaimCaseEmail)
        .filter(
            ClaimCaseEmail.claim_case_id == claim_case_id,
            ClaimCaseEmail.email_type.in_(_APPROVAL_EMAIL_TYPES),
        )
        .order_by(ClaimCaseEmail.created_at.desc())
        .first()
    )
    if not email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim case has no approval email yet — nothing to generate a Part-D for",
        )
    return email


def _to_response(part_d: PartDLetter) -> PartDLetterResponse:
    resp = PartDLetterResponse.model_validate(part_d)
    resp.is_persisted = True
    return resp


def _stub_response(claim_case: ClaimCase, email: ClaimCaseEmail) -> PartDLetterResponse:
    """A not-yet-persisted Part-D prefilled from the claim. The modal renders
    from this on first open; nothing is written until a PUT."""
    return PartDLetterResponse(
        claim_case_id=claim_case.id,
        claim_case_email_id=email.id,
        approved_amount=(
            float(claim_case.approved_amount)
            if claim_case.approved_amount is not None else None
        ),
        claim_number=claim_case.claim_number,
        is_persisted=False,
    )


def get_part_d(
    db: Session, claim_case_id, email_id: int | None = None, current_user=None
) -> PartDLetterResponse:
    claim_case = _get_claim_case(db, claim_case_id, current_user)
    email = _resolve_approval_email(db, claim_case_id, email_id)
    part_d = (
        db.query(PartDLetter)
        .filter(PartDLetter.claim_case_email_id == email.id)
        .first()
    )
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
    """Create or update the Part-D for the resolved approval email.

    `fields` is a dict of {field_name: value} — only keys present are applied
    (partial update). If a file is provided it's saved, attached to the
    approval email as a ClaimCaseEmailAttachment, and linked via attachment_id.
    """
    claim_case = _get_claim_case(db, claim_case_id, current_user)
    email = _resolve_approval_email(db, claim_case_id, email_id)

    part_d = (
        db.query(PartDLetter)
        .filter(PartDLetter.claim_case_email_id == email.id)
        .first()
    )
    if not part_d:
        part_d = PartDLetter(
            claim_case_id=claim_case.id,
            claim_case_email_id=email.id,
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
