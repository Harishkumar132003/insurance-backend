import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.hospital_provider_mapping import HospitalProviderMapping
from app.models.policy_provider_config import PolicyProviderConfig
from app.schemas.hospital_provider import HospitalProviderUpdate
from app.services.mou_extraction_service import extract_mou_data
from app.utils.file_storage import save_mou


def extract_mou(file_bytes: bytes, file_name: str | None, content_type: str | None) -> dict:
    return extract_mou_data(file_bytes, file_name, content_type)


def _serialize(mapping: HospitalProviderMapping, provider: PolicyProviderConfig) -> dict:
    return {
        "id": mapping.id,
        "hospital_id": mapping.hospital_id,
        "policy_provider_id": mapping.policy_provider_id,
        "provider_name": provider.name,
        "provider_external_id": provider.provider_id,
        "email": provider.email,
        "tpa_name": provider.tpa_name,
        "tpa_toll_free_phone": provider.tpa_toll_free_phone,
        "tpa_toll_free_fax": provider.tpa_toll_free_fax,
        "room_charges": mapping.room_charges,
        "mou_original_filename": mapping.mou_original_filename,
        "is_active": mapping.is_active,
        "created_at": mapping.created_at,
        "updated_at": mapping.updated_at,
    }


def list_for_hospital(db: Session, hospital_id) -> list[dict]:
    rows = (
        db.query(HospitalProviderMapping, PolicyProviderConfig)
        .join(
            PolicyProviderConfig,
            PolicyProviderConfig.id == HospitalProviderMapping.policy_provider_id,
        )
        .filter(HospitalProviderMapping.hospital_id == hospital_id)
        .order_by(HospitalProviderMapping.created_at.desc())
        .all()
    )
    return [_serialize(m, p) for m, p in rows]


def list_onboarded_providers(db: Session, hospital_id) -> list[dict]:
    """Providers mapped to this hospital AND flagged is_onboarded, each with the
    MOU room charges — feeds the pre-auth provider selector + Room Type dropdown."""
    rows = (
        db.query(PolicyProviderConfig, HospitalProviderMapping)
        .join(
            HospitalProviderMapping,
            HospitalProviderMapping.policy_provider_id == PolicyProviderConfig.id,
        )
        .filter(
            HospitalProviderMapping.hospital_id == hospital_id,
            HospitalProviderMapping.is_active.is_(True),
            PolicyProviderConfig.is_onboarded.is_(True),
        )
        .order_by(PolicyProviderConfig.name)
        .all()
    )
    return [
        {
            "id": p.id,
            "provider_id": p.provider_id,
            "name": p.name,
            "email": p.email,
            "tpa_name": p.tpa_name,
            "tpa_toll_free_phone": p.tpa_toll_free_phone,
            "tpa_toll_free_fax": p.tpa_toll_free_fax,
            "room_charges": m.room_charges,
        }
        for p, m in rows
    ]


def list_available_providers(db: Session, hospital_id) -> list[PolicyProviderConfig]:
    """Onboarded providers NOT yet mapped to this hospital — the catalog the
    admin can pick from instead of typing fresh details."""
    mapped_ids = (
        db.query(HospitalProviderMapping.policy_provider_id)
        .filter(HospitalProviderMapping.hospital_id == hospital_id)
        .subquery()
    )
    return (
        db.query(PolicyProviderConfig)
        .filter(
            PolicyProviderConfig.is_onboarded.is_(True),
            PolicyProviderConfig.id.notin_(mapped_ids),
        )
        .order_by(PolicyProviderConfig.name)
        .all()
    )


def _get_mapping(db: Session, hospital_id, mapping_id) -> HospitalProviderMapping:
    mapping = (
        db.query(HospitalProviderMapping)
        .filter(
            HospitalProviderMapping.id == mapping_id,
            HospitalProviderMapping.hospital_id == hospital_id,
        )
        .first()
    )
    if not mapping:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider mapping not found")
    return mapping


def create_mapping(
    db: Session,
    hospital_id,
    provider_name: str | None,
    provider_external_id: str | None,
    email: str | None,
    tpa_name: str | None,
    tpa_toll_free_phone: str | None,
    tpa_toll_free_fax: str | None,
    room_charges: dict | None,
    mou_bytes: bytes | None,
    mou_filename: str | None,
    mou_content_type: str | None,
    existing_provider_id=None,
) -> dict:
    if existing_provider_id:
        provider = (
            db.query(PolicyProviderConfig)
            .filter(
                PolicyProviderConfig.id == existing_provider_id,
                PolicyProviderConfig.is_onboarded.is_(True),
            )
            .first()
        )
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Onboarded provider not found",
            )
        already = (
            db.query(HospitalProviderMapping)
            .filter(
                HospitalProviderMapping.hospital_id == hospital_id,
                HospitalProviderMapping.policy_provider_id == provider.id,
            )
            .first()
        )
        if already:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider is already onboarded to this hospital",
            )
    else:
        if not (provider_name or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider name is required",
            )
        provider_id_str = (provider_external_id or "").strip() or f"PROV-{uuid.uuid4().hex[:8].upper()}"
        if db.query(PolicyProviderConfig).filter(
            PolicyProviderConfig.provider_id == provider_id_str
        ).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Provider ID '{provider_id_str}' already exists",
            )

        provider = PolicyProviderConfig(
            provider_id=provider_id_str,
            name=provider_name,
            email=email,
            tpa_name=tpa_name,
            tpa_toll_free_phone=tpa_toll_free_phone,
            tpa_toll_free_fax=tpa_toll_free_fax,
            is_onboarded=True,
            config={"auth": None, "steps": [], "required_fields": []},
        )
        db.add(provider)
        db.flush()

    mapping = HospitalProviderMapping(
        hospital_id=hospital_id,
        policy_provider_id=provider.id,
        room_charges=room_charges,
        extracted_data=room_charges,
    )
    if mou_bytes and mou_filename:
        stored_filename, file_path = save_mou(hospital_id, mou_bytes, mou_filename)
        mapping.mou_original_filename = mou_filename
        mapping.mou_stored_filename = stored_filename
        mapping.mou_file_path = file_path
        mapping.mou_content_type = mou_content_type
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    db.refresh(provider)
    return _serialize(mapping, provider)


def update_mapping(db: Session, hospital_id, mapping_id, payload: HospitalProviderUpdate) -> dict:
    mapping = _get_mapping(db, hospital_id, mapping_id)
    provider = (
        db.query(PolicyProviderConfig)
        .filter(PolicyProviderConfig.id == mapping.policy_provider_id)
        .first()
    )

    if payload.provider_name is not None:
        provider.name = payload.provider_name
    if payload.email is not None:
        provider.email = payload.email
    if payload.tpa_name is not None:
        provider.tpa_name = payload.tpa_name
    if payload.tpa_toll_free_phone is not None:
        provider.tpa_toll_free_phone = payload.tpa_toll_free_phone
    if payload.tpa_toll_free_fax is not None:
        provider.tpa_toll_free_fax = payload.tpa_toll_free_fax
    if payload.room_charges is not None:
        mapping.room_charges = payload.room_charges.model_dump()
        flag_modified(mapping, "room_charges")
    if payload.is_active is not None:
        mapping.is_active = payload.is_active

    db.commit()
    db.refresh(mapping)
    db.refresh(provider)
    return _serialize(mapping, provider)


def get_mapping_for_mou(db: Session, hospital_id, mapping_id) -> HospitalProviderMapping:
    mapping = _get_mapping(db, hospital_id, mapping_id)
    if not mapping.mou_file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No MOU on file")
    return mapping


def delete_mapping(db: Session, hospital_id, mapping_id) -> dict:
    mapping = _get_mapping(db, hospital_id, mapping_id)
    db.delete(mapping)
    db.commit()
    return {"detail": "Provider unassigned"}
