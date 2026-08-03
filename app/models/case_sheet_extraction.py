import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class CaseSheetExtraction(Base):
    """One AI read of an uploaded case sheet: the source PDF plus what was pulled
    out of it, kept together as the audit trail behind a pre-filled form.

    Created at extract time, before any claim case exists — `claim_case_id` stays
    NULL until the form is first saved. Same two-phase shape as the settlement
    flow, and the same four file columns as the MOU on hospital_provider_mappings.

    This is an audit record, NOT a source of truth: the values the user keeps are
    saved into the pre_auth_* tables by the normal form save.
    """
    __tablename__ = "case_sheet_extraction"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hospital_id = Column(UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=False)
    # Set once the form built from this sheet is saved. NULL means the upload was
    # abandoned before a case was created.
    claim_case_id = Column(UUID(as_uuid=True), ForeignKey("hospitalization.id"), nullable=True)

    # Every uploaded page, in upload order: {original_filename, stored_filename,
    # file_path, content_type, size}. A case sheet is often several photos.
    files = Column(JSONB, nullable=True)
    # Page 1, mirrored — keeps the single-file read paths and the rows written
    # before multi-file support working unchanged.
    original_filename = Column(String, nullable=True)
    stored_filename = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    content_type = Column(String, nullable=True)

    summary = Column(Text, nullable=True)
    # Flat {form field key -> value}, exactly what pre-filled the form.
    extracted = Column(JSONB, nullable=True)
    # {form field key -> {confidence: HIGH|MEDIUM|LOW, source: "<verbatim line>"}}
    # Only for fields that actually produced a value.
    field_meta = Column(JSONB, nullable=True)
    # The repeatable groups, stored for audit. Not scored.
    treatments = Column(JSONB, nullable=True)
    investigations = Column(JSONB, nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_case_sheet_extraction_hospital_id", "hospital_id"),
        Index("ix_case_sheet_extraction_claim_case_id", "claim_case_id"),
    )
