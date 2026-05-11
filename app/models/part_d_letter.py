from sqlalchemy import Column, BigInteger, Numeric, String, Text, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class PartDLetter(Base):
    """Editable field values for a Part-D (Cashless Authorization Letter).

    One row per approval-round email (the APPROVAL / PARTIAL_APPROVAL
    ClaimCaseEmail). Lets the provider's Part-D modal prefill instead of
    re-typing the bill breakdown / authorization summary each time. The
    bill/summary columns are free text because the PDF renders them verbatim
    (e.g. "Rs.5,000/day", "Package", "N/A").
    """
    __tablename__ = "part_d_letters"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    claim_case_id = Column(UUID(as_uuid=True), ForeignKey("claim_cases.id"), nullable=False)
    claim_case_email_id = Column(BigInteger, ForeignKey("claim_case_emails.id"), nullable=False)
    # The rendered PDF, attached to the approval email; set on first print/download.
    attachment_id = Column(BigInteger, ForeignKey("claim_case_email_attachments.id"), nullable=True)

    # Header overrides — mirror the claim but frozen on the letter.
    approved_amount = Column(Numeric(12, 2), nullable=True)
    claim_number = Column(String, nullable=True)

    # Bill breakdown.
    room_rent_per_day = Column(String, nullable=True)
    icu_rent_per_day = Column(String, nullable=True)
    nursing_charges_per_day = Column(String, nullable=True)
    consultant_visit_charges_per_day = Column(String, nullable=True)
    surgeon_anesthetist_fee = Column(String, nullable=True)
    others = Column(String, nullable=True)

    # Authorization summary.
    total_bill_amount = Column(String, nullable=True)
    deductions_detail = Column(String, nullable=True)
    discount = Column(String, nullable=True)
    co_pay = Column(String, nullable=True)
    deductibles = Column(String, nullable=True)
    total_authorised_amount = Column(String, nullable=True)
    amount_to_be_paid_by_insured = Column(String, nullable=True)

    remarks = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    claim_case = relationship("ClaimCase")
    email = relationship("ClaimCaseEmail")
    attachment = relationship("ClaimCaseEmailAttachment")

    __table_args__ = (
        UniqueConstraint("claim_case_email_id", name="uq_part_d_letter_email"),
        Index("ix_part_d_letters_claim_case_id", "claim_case_id"),
    )
