from sqlalchemy import Column, BigInteger, String, Numeric, Boolean, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class SettlementItem(Base):
    """One claim line within a settlement batch.

    `claim_case_id` is the mapping to `hospitalization`, resolved on save by
    matching `claim_number`. Nullable: a line whose claim number isn't found is
    still stored (flagged unmatched) so nothing is lost.
    """

    __tablename__ = "settlement_item"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("settlement_batch.id", ondelete="CASCADE"),
        nullable=False,
    )

    claim_number = Column(String, nullable=True)
    settled_amount = Column(Numeric(14, 2), nullable=True)
    claim_raised_amount = Column(Numeric(14, 2), nullable=True)
    disallowance = Column(Numeric(14, 2), nullable=True)
    disallowance_reason = Column(String, nullable=True)

    # Mapping to the claim case (matched on claim_number at save time). DB column
    # is `hospitalization_id`; ORM attribute stays `claim_case_id` (code unchanged).
    claim_case_id = Column("hospitalization_id", UUID(as_uuid=True), ForeignKey("hospitalization.id"), nullable=True)
    is_matched = Column(Boolean, nullable=False, default=False)

    # Denormalised for easy lookup, kept in sync by a DB trigger:
    #   hospital_id = the batch's hospital (always set)
    #   uhid        = the matched case's UHID (NULL when unmatched)
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=True)
    uhid = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    batch = relationship("SettlementBatch", back_populates="items")

    __table_args__ = (
        Index("ix_settlement_item_batch_id", "batch_id"),
        Index("ix_settlement_item_hospitalization_id", claim_case_id),
        Index("ix_settlement_item_claim_number", "claim_number"),
        Index("ix_settlement_item_hospital_id", "hospital_id"),
    )
