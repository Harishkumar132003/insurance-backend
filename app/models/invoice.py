from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Invoice(Base):
    """Internal invoice raised by the hospital against an approved claim.

    One invoice per claim case. Status is auto-derived from payments:
      sum(payments) == 0              → UNPAID
      0 < sum < insurer_amount        → PARTIALLY_PAID
      sum >= insurer_amount           → PAID
    Payments live in `invoice_payment` (N per invoice). Each payment carries
    its own reference_id (UTR / settlement id / etc.).
    """
    __tablename__ = "invoice"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(
        UUID(as_uuid=True),
        ForeignKey("hospitalization.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    insurer_invoice_id = Column(String, nullable=False)
    insurer_amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String, nullable=False, default="UNPAID")
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    payments = relationship(
        "InvoicePayment",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoicePayment.sort_order",
    )

    __table_args__ = (
        Index("ix_invoice_status", "status"),
    )
