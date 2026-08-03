"""Signed, expiring links for files that must be fetched without a login.

Used for case-sheet page images: OpenAI's servers download the image themselves,
and they will not send an Authorization header, so the URL has to work
unauthenticated.

Rather than exposing the files outright, each link carries an expiry and an HMAC
over (resource, index, expiry) keyed on SECRET_KEY. A link cannot be forged, can
be issued only by this server, and stops working within minutes — so a URL that
leaks into a log, a proxy cache or a bug report is inert by the time anyone finds
it. These are patient documents; an unguessable id alone is not much of a control.
"""
import hashlib
import hmac
import time

from app.core.config import settings

_SEP = ":"


def _digest(resource: str, index: int, expires_at: int) -> str:
    payload = f"{resource}{_SEP}{index}{_SEP}{expires_at}".encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()[:32]


def sign(resource: str, index: int, ttl_seconds: int | None = None) -> tuple[int, str]:
    """Return (expires_at, signature) for one file."""
    ttl = ttl_seconds or settings.CASE_SHEET_LINK_TTL_SECONDS
    expires_at = int(time.time()) + ttl
    return expires_at, _digest(resource, index, expires_at)


def verify(resource: str, index: int, expires_at: int, signature: str) -> bool:
    """True when the signature matches and the link has not expired."""
    if not signature or expires_at < int(time.time()):
        return False
    return hmac.compare_digest(_digest(resource, index, expires_at), signature)
