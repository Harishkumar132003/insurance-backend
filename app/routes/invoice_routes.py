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
    InvoiceReferenceUpdate,
    InvoiceResponse,
    InvoiceStatusUpdate,
)

router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.get("", response_model=list[InvoiceListItem])
def list_invoices(
    scope: str = Query(default="to_invoice", description="to_invoice | invoiced"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return invoice_controller.list_for_hospital(db, current_user, scope=scope)


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


@router.patch("/{claim_case_id}/status", response_model=InvoiceResponse)
def update_invoice_status(
    claim_case_id: UUID,
    payload: InvoiceStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return invoice_controller.update_status(db, claim_case_id, payload.status, current_user)


@router.patch("/{claim_case_id}/reference", response_model=InvoiceResponse)
def update_invoice_reference(
    claim_case_id: UUID,
    payload: InvoiceReferenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return invoice_controller.update_reference(
        db, claim_case_id, payload.reference_id, current_user
    )
