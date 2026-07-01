"""add policy_provider_id to settlement_batch (+ fuzzy backfill from tpa_insurer)

Adds a structured provider link to the settlement batch. AI-suggested from the
extracted tpa_insurer on upload (editable in the UI). Existing rows are
backfilled by fuzzy-matching tpa_insurer against the hospital's mapped providers'
name / tpa_name.

Revision ID: b5d9c3e7a1f2
Revises: a2e6c4b8d1f3
Create Date: 2026-07-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'b5d9c3e7a1f2'
down_revision = 'a2e6c4b8d1f3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('settlement_batch',
                  sa.Column('policy_provider_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_settlement_batch_policy_provider_id', 'settlement_batch',
        'policy_provider_configs', ['policy_provider_id'], ['id'])
    op.create_index('ix_settlement_batch_policy_provider_id',
                    'settlement_batch', ['policy_provider_id'])

    # Backfill: match tpa_insurer -> a provider mapped to the batch's hospital,
    # preferring exact name match, then substring either direction (name/tpa_name).
    op.execute("""
        UPDATE settlement_batch b SET policy_provider_id = sub.pid
        FROM (
            SELECT DISTINCT ON (b2.id) b2.id AS bid, p.id AS pid
              FROM settlement_batch b2
              JOIN hospital_provider_mappings m ON m.hospital_id = b2.hospital_id
              JOIN policy_provider_configs p ON p.id = m.policy_provider_id
             WHERE b2.tpa_insurer IS NOT NULL AND btrim(b2.tpa_insurer) <> ''
               AND (
                   lower(p.name) = lower(b2.tpa_insurer)
                   OR p.name ILIKE '%' || b2.tpa_insurer || '%'
                   OR b2.tpa_insurer ILIKE '%' || p.name || '%'
                   OR (p.tpa_name IS NOT NULL AND (
                        p.tpa_name ILIKE '%' || b2.tpa_insurer || '%'
                        OR b2.tpa_insurer ILIKE '%' || p.tpa_name || '%'))
               )
             ORDER BY b2.id,
                      (lower(p.name) = lower(b2.tpa_insurer)) DESC,
                      length(p.name) DESC
        ) sub
        WHERE b.id = sub.bid
    """)


def downgrade():
    op.drop_index('ix_settlement_batch_policy_provider_id', table_name='settlement_batch')
    op.drop_constraint('fk_settlement_batch_policy_provider_id', 'settlement_batch', type_='foreignkey')
    op.drop_column('settlement_batch', 'policy_provider_id')
