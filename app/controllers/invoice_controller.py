"""Invoice flow — post-claim-approval settlement record.

A case enters the invoice stage when its `claims.approved_amount > 0`. The
hospital admin raises ONE invoice per case capturing what was billed to the
insurer + the payments collected against it. Status (PAID / PARTIALLY_PAID /
UNPAID) is auto-derived from the sum of payments and the insurer amount on
every write. This is a pure internal record: no email, no provider interaction.
"""

from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
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
    InvoiceCreate,
    InvoiceListItem,
    InvoicePaymentIn,
    InvoicePaymentUpdate,
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


def _derive_status(invoice: Invoice) -> str:
    """Compute invoice.status from its payments. Called after every write."""
    paid_total = sum(
        (Decimal(str(p.amount)) for p in invoice.payments if p.amount is not None),
        Decimal("0"),
    )
    insurer = Decimal(str(invoice.insurer_amount or 0))
    if paid_total <= 0:
        return "UNPAID"
    if insurer > 0 and paid_total >= insurer:
        return "PAID"
    return "PARTIALLY_PAID"


def _recompute_status(invoice: Invoice) -> None:
    invoice.status = _derive_status(invoice)


def _validate_payment_amount(amount) -> None:
    if amount is None or Decimal(str(amount)) <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Payment amount must be greater than zero",
        )


def _get_invoice_or_404(db: Session, claim_case_id: UUID) -> Invoice:
    invoice = (
        db.query(Invoice).filter(Invoice.claim_case_id == claim_case_id).first()
    )
    if not invoice:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="No invoice raised for this case yet",
        )
    return invoice


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
        status="UNPAID",
        created_by_user_id=current_user.id,
    )
    db.add(invoice)
    db.flush()

    for idx, pay in enumerate(payload.payments or []):
        _validate_payment_amount(pay.amount)
        db.add(InvoicePayment(
            invoice_id=invoice.id,
            payment_date=pay.payment_date,
            amount=pay.amount,
            reference_id=(pay.reference_id or "").strip() or None,
            note=(pay.note or "").strip() or None,
            sort_order=idx,
        ))

    db.flush()
    db.refresh(invoice)
    _recompute_status(invoice)

    db.commit()
    db.refresh(invoice)
    return _serialize_invoice(invoice)


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
    invoice = _get_invoice_or_404(db, claim_case_id)

    _validate_payment_amount(payment.amount)
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
        reference_id=(payment.reference_id or "").strip() or None,
        note=(payment.note or "").strip() or None,
        sort_order=sort_order,
    ))
    db.flush()
    db.refresh(invoice)
    _recompute_status(invoice)

    db.commit()
    db.refresh(invoice)
    return _serialize_invoice(invoice)


def update_payment(
    db: Session,
    claim_case_id: UUID,
    payment_id: int,
    payload: InvoicePaymentUpdate,
    current_user: User,
) -> InvoiceResponse:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )
    _scope_to_hospital(claim_case, current_user)
    invoice = _get_invoice_or_404(db, claim_case_id)

    payment = (
        db.query(InvoicePayment)
        .filter(InvoicePayment.id == payment_id, InvoicePayment.invoice_id == invoice.id)
        .first()
    )
    if not payment:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )

    fields = payload.model_fields_set
    if "payment_date" in fields and payload.payment_date is not None:
        payment.payment_date = payload.payment_date
    if "amount" in fields and payload.amount is not None:
        _validate_payment_amount(payload.amount)
        payment.amount = payload.amount
    if "reference_id" in fields:
        # Empty/whitespace → clear it.
        payment.reference_id = (payload.reference_id or "").strip() or None
    if "note" in fields:
        payment.note = (payload.note or "").strip() or None

    db.flush()
    db.refresh(invoice)
    _recompute_status(invoice)

    db.commit()
    db.refresh(invoice)
    return _serialize_invoice(invoice)


def delete_payment(
    db: Session,
    claim_case_id: UUID,
    payment_id: int,
    current_user: User,
) -> InvoiceResponse:
    claim_case = db.query(ClaimCase).filter(ClaimCase.id == claim_case_id).first()
    if not claim_case:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Claim case not found",
        )
    _scope_to_hospital(claim_case, current_user)
    invoice = _get_invoice_or_404(db, claim_case_id)

    payment = (
        db.query(InvoicePayment)
        .filter(InvoicePayment.id == payment_id, InvoicePayment.invoice_id == invoice.id)
        .first()
    )
    if not payment:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )

    db.delete(payment)
    db.flush()
    db.refresh(invoice)
    _recompute_status(invoice)

    db.commit()
    db.refresh(invoice)
    return _serialize_invoice(invoice)


def list_for_hospital(
    db: Session,
    current_user: User,
    *,
    scope: str = "to_invoice",
    q: str | None = None,
) -> list[InvoiceListItem]:
    """List cases relevant to the Raise Invoice tab.

    scope='to_invoice' — claim-approved cases with NO invoice yet.
    scope='invoiced'   — cases that already have an invoice.
    q                  — optional substring filter on uhid / patient_name /
                         claim_number (and insurer_invoice_id when scope='invoiced').
    """
    if current_user.role != "HOSPITAL_ADMIN":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only hospital admins can view the invoice queue",
        )

    query = (
        db.query(ClaimCase, Claim, Invoice)
        .join(Claim, Claim.claim_case_id == ClaimCase.id)
        .outerjoin(Invoice, Invoice.claim_case_id == ClaimCase.id)
        .filter(ClaimCase.hospital_id == current_user.hospital_id)
        .filter(ClaimCase.status != "CANCELLED")
        .filter(Claim.approved_amount.isnot(None))
        .filter(Claim.approved_amount > 0)
    )
    if scope == "to_invoice":
        query = query.filter(Invoice.id.is_(None))
    elif scope == "invoiced":
        query = query.filter(Invoice.id.isnot(None))
    else:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="scope must be 'to_invoice' or 'invoiced'",
        )

    # Case-insensitive substring search across uhid / patient_name /
    # claim_number, plus insurer_invoice_id when the row has an invoice.
    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        patient_match = (
            sa.exists()
            .where(FormData.claim_case_id == ClaimCase.id)
            .where(PreAuthPatient.form_data_id == FormData.id)
            .where(PreAuthPatient.patient_name.ilike(like))
        )
        clauses = [
            ClaimCase.uhid.ilike(like),
            ClaimCase.claim_number.ilike(like),
            patient_match,
        ]
        if scope == "invoiced":
            clauses.append(Invoice.insurer_invoice_id.ilike(like))
        query = query.filter(sa.or_(*clauses))

    rows = query.order_by(ClaimCase.created_at.desc()).all()

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
