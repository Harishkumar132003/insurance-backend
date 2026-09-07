"""consolidated ai-chat DB structure onto the merge-chat feature set

Squashes the 24 migrations that existed only on `ai-chat` into one revision, so
the merged branch keeps a single linear alembic history instead of two heads.

Scoped to the ACTUAL delta. Most of ai-chat's additive work (preauth_raised_amount,
hospital_id on the case tables, claims.uhid/claim_number, settlement_item.uhid,
settlement_batch.policy_provider_id, preauth_status_tracking, claim_status_tracking,
patient_personal_detail) is ALREADY present in a merge-chat database, so replaying
those steps verbatim just errors on "column already exists". What genuinely
remains is the four renames, the claim-model change, the drops, and the trigger
rewrites.

Every step is guarded, so this is safe to re-run and safe on a database that has
some of it already.

Ordering is load-bearing: the patient-table consolidation reads pre_auth's OLD
column name and must run BEFORE the renames; the claim_bill_item backfill reads
the NEW name and must run after.

merge-chat's own additions (cost_items, bd_items, case_sheet_extraction) target
tables this migration never touches.

NOTE: a database already at ai-chat head c6e0f4a8b2d5 (e.g. `oasysbackup`) should
be `alembic stamp`-ed to this revision, not upgraded.

Revision ID: a1b2c3d4e5f7
Revises: f4a8c1e7b309
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f7"
down_revision = "f4a8c1e7b309"
branch_labels = None
depends_on = None


# ── guards ────────────────────────────────────────────────────────────
def _insp():
    return sa.inspect(op.get_bind())


def _has_table(t: str) -> bool:
    return t in _insp().get_table_names()


def _has_column(t: str, c: str) -> bool:
    return _has_table(t) and c in {x["name"] for x in _insp().get_columns(t)}


# Columns shared by pre_auth_patient and patient_personal_detail. varchar vs
# text on both sides; Postgres casts implicitly.
_PATIENT_COLS = [
    "form_data_id", "patient_name", "gender", "address", "age_years",
    "occupation", "employee_id", "date_of_birth", "policy_number",
    "contact_number", "corporate_name", "insured_card_id",
    "has_other_insurance", "has_family_physician", "family_physician_name",
    "family_physician_contact", "other_insurance_company",
    "other_insurance_details", "relative_contact_number",
]


def upgrade() -> None:
    # ── 1. Consolidate the duplicate patient tables ───────────────────
    # Both tables exist on a merge-chat DB: the code wrote pre_auth_patient
    # while patient_personal_detail held the older rows. The merged models read
    # only patient_personal_detail, so anything left behind would go invisible.
    # Runs BEFORE the renames — it reads pre_auth.claim_case_id.
    if _has_table("pre_auth_patient") and _has_table("patient_personal_detail"):
        cols = [c for c in _PATIENT_COLS if _has_column("pre_auth_patient", c)
                and _has_column("patient_personal_detail", c)]
        collist = ", ".join(cols)
        srclist = ", ".join(f"p.{c}" for c in cols)
        op.execute(f"""
            INSERT INTO patient_personal_detail ({collist}, hospitalization_id, uhid)
            SELECT {srclist}, f.claim_case_id, h.uhid
              FROM pre_auth_patient p
              JOIN pre_auth f ON f.id = p.form_data_id
              LEFT JOIN hospitalization h ON h.id = f.claim_case_id
             WHERE NOT EXISTS (SELECT 1 FROM patient_personal_detail d
                                WHERE d.form_data_id = p.form_data_id)
        """)
        op.execute("DROP TABLE pre_auth_patient CASCADE")

    # ── 2. claim_case_id -> hospitalization_id ────────────────────────
    # The ORM keeps the attribute name via Column("hospitalization_id", ...),
    # so application code is unaffected; only raw SQL had to change.
    for table in ("pre_auth", "claims", "settlement_item"):
        if _has_column(table, "claim_case_id") and not _has_column(table, "hospitalization_id"):
            op.alter_column(table, "claim_case_id", new_column_name="hospitalization_id")
    # Constraint/index names are already *_hospitalization_id_* on a merge-chat
    # DB (they were renamed ahead of the columns), so these are guarded no-ops.
    op.execute("""
    DO $$
    DECLARE r record;
    BEGIN
        FOR r IN SELECT conname, conrelid::regclass::text AS tbl FROM pg_constraint
                  WHERE conname LIKE '%claim_case_id%'
                    AND connamespace = 'public'::regnamespace
                    AND conrelid::regclass::text IN ('pre_auth','claims','settlement_item')
        LOOP
            EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I',
                           r.tbl, r.conname, replace(r.conname,'claim_case_id','hospitalization_id'));
        END LOOP;
        FOR r IN SELECT indexname, tablename FROM pg_indexes
                  WHERE schemaname='public' AND indexname LIKE '%claim_case_id%'
                    AND tablename IN ('pre_auth','claims','settlement_item')
        LOOP
            EXECUTE format('ALTER INDEX %I RENAME TO %I',
                           r.indexname, replace(r.indexname,'claim_case_id','hospitalization_id'));
        END LOOP;
    END $$;
    """)

    # ── 3. Re-anchor claim_bill_item on the case ──────────────────────
    # ai-chat's model: bill lines belong to the case, not to a CLAIM-stage form
    # row. Backfill BEFORE dropping form_data_id, and drop the RLS policy first
    # because it scopes through the column being removed.
    if not _has_column("claim_bill_item", "hospitalization_id"):
        op.execute("ALTER TABLE claim_bill_item ADD COLUMN hospitalization_id UUID")
        op.execute("""
            UPDATE claim_bill_item b
               SET hospitalization_id = p.hospitalization_id
              FROM pre_auth p
             WHERE p.id = b.form_data_id
        """)
        op.execute("DELETE FROM claim_bill_item WHERE hospitalization_id IS NULL")
        op.execute("DROP POLICY IF EXISTS ai_ro_tenant ON public.claim_bill_item")
        # Dropping form_data_id also drops its CASCADE FK, so the CLAIM pre_auth
        # deletes in step 4 cannot cascade away the re-anchored bill lines.
        if _has_column("claim_bill_item", "form_data_id"):
            op.execute("ALTER TABLE claim_bill_item DROP COLUMN form_data_id")
        op.execute("ALTER TABLE claim_bill_item ALTER COLUMN hospitalization_id SET NOT NULL")
        op.execute("""
            ALTER TABLE claim_bill_item
              ADD CONSTRAINT fk_claim_bill_item_hospitalization
              FOREIGN KEY (hospitalization_id) REFERENCES hospitalization(id) ON DELETE CASCADE
        """)
        op.execute("""CREATE INDEX IF NOT EXISTS ix_claim_bill_item_hospitalization_id
                        ON claim_bill_item (hospitalization_id)""")
        op.execute("""
            DO $$ BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='oasys_ai_ro') THEN
                EXECUTE 'CREATE POLICY ai_ro_tenant ON public.claim_bill_item
                           FOR SELECT TO oasys_ai_ro
                           USING (hospitalization_id IN (
                             SELECT id FROM public.hospitalization
                              WHERE hospital_id = oasys_current_hospital()))';
              END IF;
            END $$;
        """)

    # ── 4. pre_auth is always PRE_AUTH ────────────────────────────────
    # The claim no longer gets its own form row; its data lives on claims +
    # claim_bill_item. Bill lines were re-anchored above, so this is safe.
    op.execute("DROP TRIGGER IF EXISTS trg_inherit_preauth_status ON public.pre_auth")
    op.execute("DROP FUNCTION IF EXISTS public.inherit_preauth_status()")
    if _has_column("pre_auth", "stage"):
        op.execute("DELETE FROM pre_auth WHERE stage = 'CLAIM'")
        op.execute("ALTER TABLE pre_auth DROP COLUMN stage")

    # ── 5. Drop the columns ai-chat superseded ────────────────────────
    # draft_state -> derived from preauth_status; claimed_amount/remarks live on
    # the claims row (a draft total is derived from its bill lines).
    for col in ("draft_state", "claimed_amount", "remarks"):
        if _has_column("pre_auth", col):
            op.execute(f"ALTER TABLE pre_auth DROP COLUMN {col}")

    # ── 6. Drop the deprecated settlements table ──────────────────────
    if _has_table("settlements"):
        op.execute("DROP TABLE settlements CASCADE")

    # ── 7. Rewrite the trigger functions ──────────────────────────────
    # PL/pgSQL bodies are stored as TEXT and do NOT follow a column rename, so
    # without this they keep naming claim_case_id / stage and fail on the next
    # write. Bodies taken from a database already on the ai-chat structure.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.sync_preauth_status() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    BEGIN
        UPDATE public.pre_auth SET preauth_status = NEW.case_status
         WHERE hospitalization_id = NEW.id;
        RETURN NEW;
    END;
    $func$;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION public.sync_preauth_approved_amount() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    BEGIN
        UPDATE public.pre_auth SET preauth_approved_amount = NEW.approved_amount
         WHERE hospitalization_id = NEW.id;
        RETURN NEW;
    END;
    $func$;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION public.fill_settlement_item_denorm() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    BEGIN
        SELECT b.hospital_id INTO NEW.hospital_id
          FROM public.settlement_batch b WHERE b.id = NEW.batch_id;
        IF NEW.hospitalization_id IS NOT NULL THEN
            SELECT h.uhid INTO NEW.uhid
              FROM public.hospitalization h WHERE h.id = NEW.hospitalization_id;
        ELSE
            NEW.uhid := NULL;
        END IF;
        RETURN NEW;
    END;
    $func$;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_fill_settlement_item_denorm ON public.settlement_item")
    op.execute("""
        CREATE TRIGGER trg_fill_settlement_item_denorm
        BEFORE INSERT OR UPDATE OF batch_id, hospitalization_id ON public.settlement_item
        FOR EACH ROW EXECUTE FUNCTION public.fill_settlement_item_denorm();
    """)

    # ── 8. CLAIM_-prefix claims.status ────────────────────────────────
    op.execute("""
        UPDATE claims SET status = 'CLAIM_' || status
         WHERE status IS NOT NULL AND status <> '' AND status NOT LIKE 'CLAIM_%'
    """)


def downgrade() -> None:
    # Deliberately not implemented: CLAIM-stage pre_auth rows are deleted, the
    # settlements table dropped and draft_state/claimed_amount/remarks removed.
    # A mechanical reversal would fabricate data. Restore from a dump instead.
    raise NotImplementedError("consolidated structure migration is not reversible")
