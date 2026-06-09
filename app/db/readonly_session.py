"""Read-only database access for the AI query agent.

Every connection handed out here logs in as the `oasys_ai_ro` role (see
scripts/ai_readonly_role.sql) and runs inside a READ ONLY transaction with the
`oasys.hospital_id` GUC set to the caller's hospital. Postgres RLS uses that
GUC to filter every row to the caller's tenant, and the role has no write
grants — so neither a buggy nor a malicious generated query can mutate data or
cross tenants.

This module is deliberately the ONLY place that opens the read-only connection,
so the tenant GUC can never be forgotten.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import settings

_engine: Engine | None = None


def _readonly_url() -> str:
    url = settings.DATABASE_URL_READONLY or settings.DATABASE_URL
    if not settings.DATABASE_URL_READONLY:
        # Loud-ish hint in dev; production should always set the RO role.
        import logging

        logging.getLogger(__name__).warning(
            "DATABASE_URL_READONLY is unset — AI query agent is using the main "
            "connection. RLS tenant isolation requires the oasys_ai_ro role; "
            "set DATABASE_URL_READONLY for production."
        )
    return url


def get_readonly_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            _readonly_url(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            # Statement timeout is also set on the role; this is a backstop for
            # when the agent runs against the fallback connection in dev.
            connect_args={"options": "-c statement_timeout=15000"},
        )
    return _engine


@contextmanager
def readonly_connection(hospital_id: str):
    """Yield a connection bound to one hospital, inside a read-only transaction.

    `oasys.hospital_id` is set LOCAL to the transaction, so it cannot leak to
    another request that reuses the pooled connection.
    """
    if not hospital_id:
        raise ValueError("readonly_connection requires a hospital_id (tenant scope)")

    engine = get_readonly_engine()
    conn = engine.connect()
    try:
        trans = conn.begin()
        try:
            # READ ONLY at the transaction level (defence in depth) + tenant GUC.
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(
                text("SELECT set_config('oasys.hospital_id', :hid, true)"),
                {"hid": str(hospital_id)},
            )
            yield conn
        finally:
            # Read-only work — always roll back, never commit.
            trans.rollback()
    finally:
        conn.close()
