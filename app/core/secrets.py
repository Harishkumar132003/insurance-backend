"""Obfuscation for hospital.app_password, keyed only on rohini_id.

⚠️  SECURITY NOTE
Because the key is derived purely from `rohini_id` (stored in the same DB
row as the ciphertext), anyone who reads the DB can also decrypt every
password. This is OBFUSCATION, not protection against DB compromise — it
only prevents casual reads of plain-text secrets in logs / backups /
screenshots. If you later want real protection, reintroduce a server-side
master key and HKDF it with rohini_id.
"""
import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import HTTPException, status


def _hospital_fernet(rohini_id: str) -> Fernet:
    if not rohini_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rohini_id is required to store an app password",
        )
    # HKDF turns the (variable-length) rohini_id into a deterministic 32-byte
    # key that Fernet can use. The salt is a constant — changing it would
    # invalidate every existing ciphertext.
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"hospital-app-password",
        info=rohini_id.encode("utf-8"),
    ).derive(rohini_id.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_hospital_password(plaintext: str, rohini_id: str) -> str:
    return _hospital_fernet(rohini_id).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_hospital_password(ciphertext: str, rohini_id: str) -> str:
    try:
        return _hospital_fernet(rohini_id).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored hospital app password could not be decrypted",
        ) from e
