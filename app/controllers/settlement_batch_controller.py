"""Controller for batch settlement (remittance-advice) upload & storage."""

import logging
import os
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.claim_case import ClaimCase
from app.models.settlement_batch import SettlementBatch
from app.models.settlement_item import SettlementItem
from app.schemas.settlement_batch import (
    SettlementBatchListItem,
    SettlementBatchResponse,
    SettlementExtractResponse,
    SettlementFileRef,
    SettlementHeader,
    SettlementItemResponse,
    SettlementSavePayload,
)
from app.services import settlement_extraction_service
from app.utils import file_storage

logger = logging.getLogger(__name__)


def extract(db: Session, hospital_id: UUID, file_bytes: bytes, filename: str | None,
            content_type: str | None) -> SettlementExtractResponse:
    """Parse an uploaded settlement file into editable header + items, annotate
    each line with whether its claim number matches an existing case, and store
    the file on disk so save can reference it without a re-upload.
    No settlement row is written here — this is an advisory preview."""
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file.")
    data = settlement_extraction_service.extract_settlement_data(file_bytes, filename, content_type)

    numbers = {(it.get("claim_number") or "").strip() for it in data["items"]}
    matches = _match_numbers(db, hospital_id, numbers)

    items, matched = [], 0
    for it in data["items"]:
        cn = (it.get("claim_number") or "").strip()
        cid = matches.get(cn)
        if cid:
            matched += 1
        items.append({**it, "is_matched": cid is not None, "claim_case_id": cid})

    # Persist the file now (once); save() will just record this reference.
    stored, path = file_storage.save_settlement_file(hospital_id, file_bytes, filename or "settlement")
    source = SettlementFileRef(
        original_filename=filename,
        stored_filename=stored,
        file_path=path,
        content_type=content_type,
    )

    return SettlementExtractResponse(
        header=data["header"],
        items=items,
        matched_count=matched,
        unmatched_count=len(items) - matched,
        source=source,
    )


def _safe_source(hospital_id: UUID, source: SettlementFileRef | None) -> SettlementFileRef | None:
    """Validate a file reference came from this hospital's settlements folder
    (guards against path traversal / referencing another tenant's file)."""
    if not source or not source.file_path:
        return None
    expected = os.path.normpath(os.path.join(file_storage.UPLOAD_BASE_DIR, "settlements", str(hospital_id)))
    actual = os.path.normpath(source.file_path)
    if not actual.startswith(expected + os.sep):
        logger.warning("Rejecting settlement file_path outside hospital dir: %s", source.file_path)
        return None
    if not os.path.exists(file_storage.get_attachment_full_path(actual)):
        logger.warning("Settlement file_path not found on disk: %s", source.file_path)
        return None
    return source


def match_numbers(db: Session, hospital_id: UUID, claim_numbers: list[str]) -> list[dict]:
    """Live re-check: for each claim number, report whether it maps to a case.
    Used by the review screen as the user edits claim numbers."""
    cleaned = [(cn or "").strip() for cn in claim_numbers]
    matches = _match_numbers(db, hospital_id, {cn for cn in cleaned if cn})
    return [
        {"claim_number": cn, "is_matched": cn in matches, "claim_case_id": matches.get(cn)}
        for cn in cleaned if cn
    ]


def _match_numbers(db: Session, hospital_id: UUID, numbers: set[str]) -> dict[str, UUID]:
    """Map claim_number -> hospitalization.id for this hospital. One query."""
    numbers = {n for n in numbers if n}
    if not numbers:
        return {}
    rows = (
        db.query(ClaimCase.claim_number, ClaimCase.id)
        .filter(ClaimCase.hospital_id == hospital_id)
        .filter(ClaimCase.claim_number.in_(numbers))
        .all()
    )
    return {cn: cid for cn, cid in rows if cn}


def _resolve_matches(db: Session, hospital_id: UUID, items) -> dict[str, UUID]:
    """Map claim_number -> hospitalization.id for the given line items (objects
    with a `.claim_number`). Wrapper over _match_numbers."""
    return _match_numbers(db, hospital_id, {(it.claim_number or "").strip() for it in items})


def save(db: Session, hospital_id: UUID, payload: SettlementSavePayload) -> SettlementBatchResponse:
    """Persist the batch + items, link the file stored at extract time, and map
    each line to a case via claim_number."""
    h = payload.header
    batch = SettlementBatch(
        hospital_id=hospital_id,
        tpa_insurer=h.tpa_insurer,
        total_settlement_amount=h.total_settlement_amount,
        payment_mode=h.payment_mode,
        payment_batch=h.payment_batch,
        utr_number=h.utr_number,
        settlement_number=h.settlement_number,
        settlement_date=h.settlement_date,
        hospital_account_number=h.hospital_account_number,
    )

    # Link the file that extract() already stored on disk (validated).
    src = _safe_source(hospital_id, payload.source)
    if src:
        batch.source_original_filename = src.original_filename
        batch.source_stored_filename = src.stored_filename
        batch.source_file_path = src.file_path
        batch.source_content_type = src.content_type

    matches = _resolve_matches(db, hospital_id, payload.items)
    for it in payload.items:
        cn = (it.claim_number or "").strip()
        cid = matches.get(cn)
        batch.items.append(SettlementItem(
            claim_number=it.claim_number,
            settled_amount=it.settled_amount,
            claim_raised_amount=it.claim_raised_amount,
            disallowance=it.disallowance,
            disallowance_reason=it.disallowance_reason,
            claim_case_id=cid,
            is_matched=cid is not None,
        ))

    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _to_response(batch)


def update(db: Session, hospital_id: UUID, batch_id: UUID,
           payload: SettlementSavePayload) -> SettlementBatchResponse:
    """Update a saved settlement: overwrite header fields and replace all line
    items (re-running the claim-number mapping). The stored file is untouched."""
    batch = get_batch(db, hospital_id, batch_id)

    h = payload.header
    batch.tpa_insurer = h.tpa_insurer
    batch.total_settlement_amount = h.total_settlement_amount
    batch.payment_mode = h.payment_mode
    batch.payment_batch = h.payment_batch
    batch.utr_number = h.utr_number
    batch.settlement_number = h.settlement_number
    batch.settlement_date = h.settlement_date
    batch.hospital_account_number = h.hospital_account_number

    # Replace the line items wholesale (cascade delete-orphan clears the old).
    batch.items.clear()
    matches = _resolve_matches(db, hospital_id, payload.items)
    for it in payload.items:
        cn = (it.claim_number or "").strip()
        cid = matches.get(cn)
        batch.items.append(SettlementItem(
            claim_number=it.claim_number,
            settled_amount=it.settled_amount,
            claim_raised_amount=it.claim_raised_amount,
            disallowance=it.disallowance,
            disallowance_reason=it.disallowance_reason,
            claim_case_id=cid,
            is_matched=cid is not None,
        ))

    db.commit()
    db.refresh(batch)
    return _to_response(batch)


def list_batches(db: Session, hospital_id: UUID) -> list[SettlementBatchListItem]:
    batches = (
        db.query(SettlementBatch)
        .filter(SettlementBatch.hospital_id == hospital_id)
        .order_by(SettlementBatch.created_at.desc())
        .all()
    )
    out = []
    for b in batches:
        items = b.items
        out.append(SettlementBatchListItem(
            id=b.id,
            tpa_insurer=b.tpa_insurer,
            settlement_number=b.settlement_number,
            settlement_date=b.settlement_date,
            total_settlement_amount=float(b.total_settlement_amount) if b.total_settlement_amount is not None else None,
            item_count=len(items),
            matched_count=sum(1 for i in items if i.is_matched),
            source_original_filename=b.source_original_filename,
            created_at=b.created_at,
        ))
    return out


def get_batch(db: Session, hospital_id: UUID, batch_id: UUID) -> SettlementBatch:
    batch = (
        db.query(SettlementBatch)
        .filter(SettlementBatch.id == batch_id, SettlementBatch.hospital_id == hospital_id)
        .first()
    )
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Settlement not found.")
    return batch


def get_detail(db: Session, hospital_id: UUID, batch_id: UUID) -> SettlementBatchResponse:
    return _to_response(get_batch(db, hospital_id, batch_id))


def _to_response(batch: SettlementBatch) -> SettlementBatchResponse:
    items = [
        SettlementItemResponse(
            id=i.id,
            claim_number=i.claim_number,
            settled_amount=float(i.settled_amount) if i.settled_amount is not None else None,
            claim_raised_amount=float(i.claim_raised_amount) if i.claim_raised_amount is not None else None,
            disallowance=float(i.disallowance) if i.disallowance is not None else None,
            disallowance_reason=i.disallowance_reason,
            claim_case_id=i.claim_case_id,
            is_matched=i.is_matched,
        )
        for i in batch.items
    ]
    return SettlementBatchResponse(
        id=batch.id,
        header=SettlementHeader(
            tpa_insurer=batch.tpa_insurer,
            total_settlement_amount=float(batch.total_settlement_amount) if batch.total_settlement_amount is not None else None,
            payment_mode=batch.payment_mode,
            payment_batch=batch.payment_batch,
            utr_number=batch.utr_number,
            settlement_number=batch.settlement_number,
            settlement_date=batch.settlement_date,
            hospital_account_number=batch.hospital_account_number,
        ),
        source_original_filename=batch.source_original_filename,
        items=items,
        matched_count=sum(1 for i in items if i.is_matched),
        unmatched_count=sum(1 for i in items if not i.is_matched),
        created_at=batch.created_at,
    )
