from sqlalchemy import Column, BigInteger, String, Numeric, Integer, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class ClaimBillItem(Base):
    """A single claim bill-breakdown line, anchored on the CASE (hospitalization).

    One claim per case, so all bill lines for a case's claim (draft or raised)
    live here keyed by hospitalization_id — no claim-stage pre_auth row needed.
    """
    __tablename__ = "claim_bill_item"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    hospitalization_id = Column(
        UUID(as_uuid=True), ForeignKey("hospitalization.id", ondelete="CASCADE"), nullable=False
    )
    label = Column(String, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    # Per-day lines (e.g. Non ICU Room / ICU Charges): amount == rate * days.
    # NULL for flat lines — a line is "per day" when rate is not NULL.
    rate = Column(Numeric(12, 2), nullable=True)
    days = Column(Integer, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_claim_bill_item_hospitalization_id", "hospitalization_id"),
    )
