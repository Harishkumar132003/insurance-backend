"""add hospital_id to claims, pre_auth, preauth_status_tracking, claim_status_tracking

Denormalised from the case (hospitalization.hospital_id), kept in sync by a shared
BEFORE INSERT/UPDATE trigger keyed on each table's hospitalization_id FK — so it
works for every insert path (app or trigger-written) and for future data.

Revision ID: a2e6c4b8d1f3
Revises: f9d3b7c2a5e6
Create Date: 2026-07-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'a2e6c4b8d1f3'
down_revision = 'f9d3b7c2a5e6'
branch_labels = None
depends_on = None

_TABLES = ['claims', 'pre_auth', 'preauth_status_tracking', 'claim_status_tracking']


def upgrade():
    for t in _TABLES:
        op.add_column(t, sa.Column('hospital_id', postgresql.UUID(as_uuid=True),
                                   sa.ForeignKey('hospitals.id'), nullable=True))
        op.create_index(f'ix_{t}_hospital_id', t, ['hospital_id'])

    # Shared helper: set hospital_id from the case via this row's hospitalization_id.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.fill_hospital_id_from_case() RETURNS trigger
    LANGUAGE plpgsql AS $func$
    BEGIN
        IF NEW.hospitalization_id IS NOT NULL THEN
            SELECT hospital_id INTO NEW.hospital_id
              FROM public.hospitalization WHERE id = NEW.hospitalization_id;
        END IF;
        RETURN NEW;
    END;
    $func$;
    """)

    for t in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_fill_hospital_id ON public.{t};")
        op.execute(f"""
            CREATE TRIGGER trg_fill_hospital_id
            BEFORE INSERT OR UPDATE OF hospitalization_id ON public.{t}
            FOR EACH ROW EXECUTE FUNCTION public.fill_hospital_id_from_case();
        """)
        op.execute(f"""
            UPDATE public.{t} x SET hospital_id = h.hospital_id
              FROM public.hospitalization h WHERE h.id = x.hospitalization_id
        """)


def downgrade():
    for t in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_fill_hospital_id ON public.{t};")
        op.drop_index(f'ix_{t}_hospital_id', table_name=t)
        op.drop_column(t, 'hospital_id')
    op.execute("DROP FUNCTION IF EXISTS public.fill_hospital_id_from_case();")
