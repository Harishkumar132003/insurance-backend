"""Feature-key helpers for per-user tab access.

Feature keys live in the `features` table. `users.access`:
- `None`              → full access (every active feature key)
- `[]`                → no tabs
- `["dashboard",...]` → allow-list restricted to active keys

This module is deliberately DB-driven — there is no hardcoded list of feature
keys. Admins manage the set via the `/api/v1/features` endpoints.
"""

from sqlalchemy.orm import Session


def _active_keys(db: Session) -> list[str]:
    # Local import avoids a circular import at module load time.
    from app.models.feature import Feature

    rows = (
        db.query(Feature)
        .filter(Feature.is_active.is_(True))
        .order_by(Feature.key)
        .all()
    )
    return [f.key for f in rows]


def resolve_access(db: Session, access: list[str] | None) -> list[str]:
    """Return the effective feature list for a user."""
    all_keys = _active_keys(db)
    if access is None:
        return all_keys
    allow = set(access)
    return [k for k in all_keys if k in allow]


def validate_access(db: Session, access: list[str]) -> list[str]:
    """Drop unknown / inactive keys, dedupe, preserve canonical order."""
    all_keys = _active_keys(db)
    allow = set(access)
    return [k for k in all_keys if k in allow]
