import uuid

from sqlalchemy import Column, String, Numeric, Date, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class SettlementBatch(Base):
    """One uploaded settlement / remittance advice (covers many claims).

    Distinct from the per-claim `settlements` table used by claim processing —
    this is the insurer's batch payment document parsed via AI and reviewed by
    the hospital admin. Header fields below; per-claim rows in
    `settlement_item`.
    """

    __tablename__ = "settlement_batch"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=False)

    # Header fields extracted from the document (all editable before save).
    tpa_insurer = Column(String, nullable=True)
    total_settlement_amount = Column(Numeric(14, 2), nullable=True)
    payment_mode = Column(String, nullable=True)
    payment_batch = Column(String, nullable=True)
    utr_number = Column(String, nullable=True)
    settlement_number = Column(String, nullable=True)
    settlement_date = Column(Date, nullable=True)
    hospital_account_number = Column(String, nullable=True)

    # The original uploaded file (stored on disk; path kept here).
    source_original_filename = Column(String, nullable=True)
    source_stored_filename = Column(String, nullable=True)
    source_file_path = Column(String, nullable=True)
    source_content_type = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items = relationship(
        "SettlementItem",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="SettlementItem.id",
    )

    __table_args__ = (
        Index("ix_settlement_batch_hospital_id", "hospital_id"),
    )
