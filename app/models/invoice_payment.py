from sqlalchemy import Column, BigInteger, Integer, Date, Numeric, String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class InvoicePayment(Base):
    """A single payment line under an Invoice. Replaces the array shape from
    the modal — N rows per invoice, in user-defined order."""
    __tablename__ = "invoice_payment"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id = Column(
        BigInteger,
        ForeignKey("invoice.id", ondelete="CASCADE"),
        nullable=False,
    )
    payment_date = Column(Date, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    reference_id = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    invoice = relationship("Invoice", back_populates="payments")

    __table_args__ = (
        Index("ix_invoice_payment_invoice_id", "invoice_id"),
    )
