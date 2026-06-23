from sqlalchemy import Column, BigInteger, Numeric, String, Text, DateTime, ForeignKey, Index, func, text
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
    claim_case_id = Column(UUID(as_uuid=True), ForeignKey("hospitalization.id"), nullable=False)
    # Nullable: the provider can save a Part-D draft before any approval round
    # exists. When the provider eventually approves, process_by_provider links
    # the draft to the newly-created approval email by setting this column.
    claim_case_email_id = Column(BigInteger, ForeignKey("claim_case_emails.id"), nullable=True)
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

    # ── Numeric bill breakdown matching the pre-auth cost estimates ──
    # Prefilled from the pre-auth costs; bd_room_rent / bd_icu_charges are
    # per-day rates (multiplied by the day counts below). The legacy free-text
    # columns above are kept for backward compatibility but no longer written.
    bd_room_rent = Column(Numeric(12, 2), nullable=True)        # per day
    bd_icu_charges = Column(Numeric(12, 2), nullable=True)      # per day
    bd_expected_days = Column(BigInteger, nullable=True)
    bd_icu_days = Column(BigInteger, nullable=True)
    bd_investigation_cost = Column(Numeric(12, 2), nullable=True)
    bd_ot_charges = Column(Numeric(12, 2), nullable=True)
    bd_professional_fees = Column(Numeric(12, 2), nullable=True)
    bd_medicines_cost = Column(Numeric(12, 2), nullable=True)
    bd_package_charges = Column(Numeric(12, 2), nullable=True)
    bd_other_expenses = Column(Numeric(12, 2), nullable=True)

    # ── Numeric authorisation summary (computed in the modal, stored here) ──
    # total_authorised == approved_amount (the canonical figure).
    as_total_bill_amount = Column(Numeric(12, 2), nullable=True)
    as_discount = Column(Numeric(12, 2), nullable=True)
    as_co_pay = Column(Numeric(12, 2), nullable=True)
    as_deductibles = Column(Numeric(12, 2), nullable=True)
    as_deductions = Column(Numeric(12, 2), nullable=True)
    as_amount_to_be_paid_by_insured = Column(Numeric(12, 2), nullable=True)

    remarks = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    claim_case = relationship("ClaimCase")
    email = relationship("ClaimCaseEmail")
    attachment = relationship("ClaimCaseEmailAttachment")

    __table_args__ = (
        # Two partial unique indexes (Postgres) so that:
        # - At most one Part-D row per approval email (post-approval letter), AND
        # - At most one draft per claim_case (pre-approval).
        Index(
            "uq_part_d_letter_email",
            "claim_case_email_id",
            unique=True,
            postgresql_where=text("claim_case_email_id IS NOT NULL"),
        ),
        Index(
            "uq_part_d_letter_draft",
            "claim_case_id",
            unique=True,
            postgresql_where=text("claim_case_email_id IS NULL"),
        ),
        Index("ix_part_d_letters_claim_case_id", "claim_case_id"),
    )
