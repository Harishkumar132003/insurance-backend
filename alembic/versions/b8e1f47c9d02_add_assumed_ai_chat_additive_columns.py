"""add the additive ai-chat columns the consolidation assumed already existed

a1b2c3d4e5f7 deliberately skipped ai-chat's ADDITIVE work, on the stated
assumption that it is "ALREADY present in a merge-chat database". That holds for
a database whose history went through ai-chat, but NOT for a clean merge-chat
database -- which never had these columns, and where nothing else creates them.
The result is a database that migrates without error yet 500s on the first
query, e.g. "column pre_auth.preauth_raised_amount does not exist".

This adds exactly the set a live server was found to be missing. Every column is
nullable and guarded with IF NOT EXISTS, so this is a no-op on a database that
already has them (one whose history did go through ai-chat) and additive
everywhere else -- no data is moved, dropped or rewritten.

Backfills are best-effort and derived from the owning hospitalization row, so
tenant scoping and the uhid/claim_number denormalisations are correct for
existing rows rather than left NULL.

Revision ID: b8e1f47c9d02
Revises: 246a33bec0bf
Create Date: 2026-09-10
"""
from alembic import op

revision = "b8e1f47c9d02"
down_revision = "246a33bec0bf"
branch_labels = None
depends_on = None

# table -> (column, DDL type)
_COLUMNS = [
    ("claims", "hospital_id", "UUID"),
    ("claims", "uhid", "VARCHAR"),
    ("claims", "claim_number", "VARCHAR"),
    ("pre_auth", "hospital_id", "UUID"),
    ("pre_auth", "preauth_raised_amount", "NUMERIC(12,2)"),
    ("pre_auth", "preauth_approved_amount", "NUMERIC(12,2)"),
    ("settlement_batch", "policy_provider_id", "UUID"),
    ("settlement_item", "hospital_id", "UUID"),
    ("settlement_item", "uhid", "VARCHAR"),
]

# column -> (referenced table, constraint name)
_FKS = {
    ("claims", "hospital_id"): ("hospitals", "fk_claims_hospital"),
    ("pre_auth", "hospital_id"): ("hospitals", "fk_pre_auth_hospital"),
    ("settlement_item", "hospital_id"): ("hospitals", "fk_settlement_item_hospital"),
    ("settlement_batch", "policy_provider_id"):
        ("policy_provider_configs", "fk_settlement_batch_policy_provider"),
}


def upgrade() -> None:
    for table, column, coltype in _COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype}"
        )

    # FKs are added separately and guarded by name: ADD COLUMN IF NOT EXISTS
    # cannot carry one, and a re-run must not fail on a duplicate constraint.
    for (table, column), (ref, name) in _FKS.items():
        op.execute(f"""
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{name}'
              ) THEN
                EXECUTE 'ALTER TABLE {table}
                           ADD CONSTRAINT {name}
                           FOREIGN KEY ({column}) REFERENCES {ref}(id)';
              END IF;
            END $$;
        """)

    # ── Backfill from the owning case, so existing rows are not left NULL ──
    op.execute("""
        UPDATE claims c SET hospital_id = h.hospital_id, uhid = h.uhid,
                            claim_number = COALESCE(c.claim_number, h.claim_number)
          FROM hospitalization h
         WHERE h.id = c.hospitalization_id
           AND (c.hospital_id IS NULL OR c.uhid IS NULL OR c.claim_number IS NULL)
    """)
    op.execute("""
        UPDATE pre_auth p SET hospital_id = h.hospital_id
          FROM hospitalization h
         WHERE h.id = p.hospitalization_id AND p.hospital_id IS NULL
    """)
    op.execute("""
        UPDATE settlement_item s SET hospital_id = h.hospital_id, uhid = h.uhid
          FROM hospitalization h
         WHERE h.id = s.hospitalization_id
           AND (s.hospital_id IS NULL OR s.uhid IS NULL)
    """)


def downgrade() -> None:
    for (table, _), (_, name) in _FKS.items():
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    for table, column, _ in _COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
