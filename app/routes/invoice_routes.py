from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.controllers import invoice_controller
from app.db.session import get_db
from app.models.user import User
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceListItem,
    InvoicePaymentIn,
    InvoicePaymentUpdate,
    InvoiceResponse,
)

router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.get("", response_model=list[InvoiceListItem])
def list_invoices(
    scope: str = Query(default="to_invoice", description="to_invoice | invoiced"),
    q: str | None = Query(default=None, description="Search by UHID / patient name / claim number / insurer invoice id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return invoice_controller.list_for_hospital(db, current_user, scope=scope, q=q)


@router.get("/{claim_case_id}", response_model=InvoiceResponse | None)
def get_invoice(
    claim_case_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return invoice_controller.get_invoice_for_case(db, claim_case_id, current_user)


@router.post("/{claim_case_id}", response_model=InvoiceResponse, status_code=201)
def raise_invoice(
    claim_case_id: UUID,
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return invoice_controller.create_invoice(db, claim_case_id, payload, current_user)


@router.post("/{claim_case_id}/payments", response_model=InvoiceResponse)
def add_invoice_payment(
    claim_case_id: UUID,
    payment: InvoicePaymentIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return invoice_controller.add_payment(db, claim_case_id, payment, current_user)


@router.patch("/{claim_case_id}/payments/{payment_id}", response_model=InvoiceResponse)
def update_invoice_payment(
    claim_case_id: UUID,
    payment_id: int,
    payload: InvoicePaymentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return invoice_controller.update_payment(
        db, claim_case_id, payment_id, payload, current_user
    )


@router.delete("/{claim_case_id}/payments/{payment_id}", response_model=InvoiceResponse)
def delete_invoice_payment(
    claim_case_id: UUID,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return invoice_controller.delete_payment(
        db, claim_case_id, payment_id, current_user
    )
