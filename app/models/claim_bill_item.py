from sqlalchemy import Column, BigInteger, String, Numeric, Integer, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class ClaimBillItem(Base):
    """A single bill-breakdown line on a claim-stage pre_auth row. Replaces the
    `data_json.bill_breakdown` array. Anchored on the pre_auth (form) row so it
    works for claim drafts too (which have no `claims` row yet)."""
    __tablename__ = "claim_bill_item"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    form_data_id = Column(BigInteger, ForeignKey("pre_auth.id", ondelete="CASCADE"), nullable=False)
    label = Column(String, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    form_data = relationship("FormData", back_populates="bill_items")

    __table_args__ = (
        Index("ix_claim_bill_item_form_data_id", "form_data_id"),
    )
