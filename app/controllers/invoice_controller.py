"""Invoice flow — post-claim-approval settlement record.

A case enters the invoice stage when its `claims.approved_amount > 0`. The
hospital admin raises ONE invoice per case capturing what was billed to the
insurer + (optionally) the payments collected against it. Status transitions
(INVOICE_RAISED ↔ PAID ↔ UNPAID) are fully manual — payments don't drive
status. This is a pure internal record: no email, no provider interaction.
"""

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.models.claim import Claim
from app.models.claim_case import ClaimCase
from app.models.invoice import Invoice
from app.models.invoice_payment import InvoicePayment
from app.models.policy_provider_config import PolicyProviderConfig
from app.models.pre_auth_patient import PreAuthPatient
from app.models.form_data import FormData
from app.models.user import User
from app.schemas.invoice import (
    INVOICE_STATUSES,
    InvoiceCreate,
    InvoiceListItem,
    InvoicePaymentIn,
    InvoiceResponse,
)


def _scope_to_hospital(claim_case: ClaimCase, current_user: User) -> None:
    if current_user.role != "HOSPITAL_ADMIN":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only hospital admins can manage invoices",
        )
    if current_user.hospital_id and claim_case.hospital_id != current_user.hospital_id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Not allowed to access this claim case",
        )


def _patient_name(db: Session, claim_case_id) -> str | None:
    """Latest PRE_AUTH form's patient name — same source the case detail uses."""
    row = (
        db.query(PreAuthPatient.patient_name)
        .join(FormData, FormData.id == PreAuthPatient.form_data_id)
        .filter(FormData.claim_case_id == claim_case_id)
        .filter(FormData.stage != "CLAIM")
        .order_by(FormData.created_at.desc())
        .first()
    )
    return row[0] if row else None


def _serialize_invoice(invoice: Invoice) -> InvoiceResponse:
    return InvoiceResponse.model_validate(invoice)


def get_invoice_for_case(
    db: Session, claim_case_id: UUID, current_user: User
) -> InvoiceResponse | None:
    """Return the invoice for a case, or None if none has been raised yet."""
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )
    _scope_to_hospital(claim_case, current_user)
    invoice = (
        db.query(Invoice).filter(Invoice.claim_case_id == claim_case_id).first()
    )
    return _serialize_invoice(invoice) if invoice else None


def create_invoice(
    db: Session,
    claim_case_id: UUID,
    payload: InvoiceCreate,
    current_user: User,
) -> InvoiceResponse:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )
    _scope_to_hospital(claim_case, current_user)

    if claim_case.status == "CANCELLED":
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Case is cancelled — invoice cannot be raised",
        )

    claim = db.query(Claim).filter(Claim.claim_case_id == claim_case_id).first()
    if not claim or not claim.approved_amount or float(claim.approved_amount) <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Invoice can only be raised on a claim with an approved amount",
        )

    if db.query(Invoice).filter(Invoice.claim_case_id == claim_case_id).first():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Invoice has already been raised for this case",
        )

    if not payload.insurer_invoice_id.strip():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="insurer_invoice_id is required",
        )
    if Decimal(str(payload.insurer_amount)) <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="insurer_amount must be greater than zero",
        )

    invoice = Invoice(
        claim_case_id=claim_case_id,
        insurer_invoice_id=payload.insurer_invoice_id.strip(),
        insurer_amount=payload.insurer_amount,
        reference_id=(payload.reference_id or None),
        status="INVOICE_RAISED",
        created_by_user_id=current_user.id,
    )
    db.add(invoice)
    db.flush()

    for idx, pay in enumerate(payload.payments or []):
        _validate_payment(pay)
        db.add(InvoicePayment(
            invoice_id=invoice.id,
            payment_date=pay.payment_date,
            amount=pay.amount,
            note=(pay.note or None),
            sort_order=idx,
        ))

    db.commit()
    db.refresh(invoice)
    return _serialize_invoice(invoice)


def _validate_payment(payment: InvoicePaymentIn) -> None:
    if Decimal(str(payment.amount)) <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Payment amount must be greater than zero",
        )


def add_payment(
    db: Session,
    claim_case_id: UUID,
    payment: InvoicePaymentIn,
    current_user: User,
) -> InvoiceResponse:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )
    _scope_to_hospital(claim_case, current_user)
    invoice = (
        db.query(Invoice).filter(Invoice.claim_case_id == claim_case_id).first()
    )
    if not invoice:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="No invoice raised for this case yet",
        )

    _validate_payment(payment)
    next_sort = (
        db.query(InvoicePayment.sort_order)
        .filter(InvoicePayment.invoice_id == invoice.id)
        .order_by(InvoicePayment.sort_order.desc())
        .first()
    )
    sort_order = (next_sort[0] + 1) if next_sort else 0

    db.add(InvoicePayment(
        invoice_id=invoice.id,
        payment_date=payment.payment_date,
        amount=payment.amount,
        note=(payment.note or None),
        sort_order=sort_order,
    ))
    db.commit()
    db.refresh(invoice)
    return _serialize_invoice(invoice)


def update_reference(
    db: Session,
    claim_case_id: UUID,
    reference_id: str | None,
    current_user: User,
) -> InvoiceResponse:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )
    _scope_to_hospital(claim_case, current_user)
    invoice = (
        db.query(Invoice).filter(Invoice.claim_case_id == claim_case_id).first()
    )
    if not invoice:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="No invoice raised for this case yet",
        )

    cleaned = (reference_id or "").strip() or None
    invoice.reference_id = cleaned
    db.commit()
    db.refresh(invoice)
    return _serialize_invoice(invoice)


def update_status(
    db: Session,
    claim_case_id: UUID,
    new_status: str,
    current_user: User,
) -> InvoiceResponse:
    if new_status not in INVOICE_STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(INVOICE_STATUSES))}",
        )

    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )
    _scope_to_hospital(claim_case, current_user)
    invoice = (
        db.query(Invoice).filter(Invoice.claim_case_id == claim_case_id).first()
    )
    if not invoice:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="No invoice raised for this case yet",
        )

    invoice.status = new_status
    db.commit()
    db.refresh(invoice)
    return _serialize_invoice(invoice)


def list_for_hospital(
    db: Session,
    current_user: User,
    *,
    scope: str = "to_invoice",
) -> list[InvoiceListItem]:
    """List cases relevant to the Raise Invoice tab.

    scope='to_invoice' — claim-approved cases with NO invoice yet.
    scope='invoiced'   — cases that already have an invoice.
    """
    if current_user.role != "HOSPITAL_ADMIN":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only hospital admins can view the invoice queue",
        )

    q = (
        db.query(ClaimCase, Claim, Invoice)
        .join(Claim, Claim.claim_case_id == ClaimCase.id)
        .outerjoin(Invoice, Invoice.claim_case_id == ClaimCase.id)
        .filter(ClaimCase.hospital_id == current_user.hospital_id)
        .filter(ClaimCase.status != "CANCELLED")
        .filter(Claim.approved_amount.isnot(None))
        .filter(Claim.approved_amount > 0)
    )
    if scope == "to_invoice":
        q = q.filter(Invoice.id.is_(None))
    elif scope == "invoiced":
        q = q.filter(Invoice.id.isnot(None))
    else:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="scope must be 'to_invoice' or 'invoiced'",
        )

    rows = q.order_by(ClaimCase.created_at.desc()).all()

    out: list[InvoiceListItem] = []
    for cc, claim, invoice in rows:
        provider = (
            db.query(PolicyProviderConfig)
            .filter(PolicyProviderConfig.id == cc.policy_provider_id)
            .first()
        )
        paid_total: float | None = None
        if invoice is not None:
            paid_total = float(
                sum((Decimal(str(p.amount)) for p in invoice.payments), Decimal("0"))
            )
        out.append(InvoiceListItem(
            claim_case_id=cc.id,
            uhid=cc.uhid,
            patient_name=_patient_name(db, cc.id),
            provider_name=provider.name if provider else None,
            claim_number=cc.claim_number if cc.claim_number and cc.claim_number != "null" else None,
            claim_raised_amount=float(claim.claimed_amount) if claim.claimed_amount is not None else None,
            claim_approved_amount=float(claim.approved_amount) if claim.approved_amount is not None else None,
            invoice_id=invoice.id if invoice else None,
            invoice_status=invoice.status if invoice else None,
            insurer_invoice_id=invoice.insurer_invoice_id if invoice else None,
            insurer_amount=float(invoice.insurer_amount) if invoice else None,
            paid_total=paid_total,
            created_at=cc.created_at,
            invoice_created_at=invoice.created_at if invoice else None,
        ))
    return out
