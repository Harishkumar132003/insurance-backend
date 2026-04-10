"""change claim_case id to uuid

Revision ID: 790db59546db
Revises: a1b2c3d4e5f6
Create Date: 2026-04-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '790db59546db'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All tables that have a foreign key to claim_cases.id
FK_TABLES = [
    ("claim_case_emails", "ix_claim_case_emails_claim_case_id"),
    ("claim_case_email_attachments", "ix_claim_case_email_attachments_claim_case_id"),
    ("claim_case_documents", None),
    ("status_history", "ix_status_history_claim_case_id"),
    ("form_data", None),
    ("query_logs", "ix_query_logs_claim_case_id"),
    ("pre_auths", None),
    ("claims", None),
]


def upgrade() -> None:
    # 1. Add new UUID column to claim_cases
    op.add_column("claim_cases", sa.Column("new_id", UUID(as_uuid=True), nullable=True))
    op.execute("UPDATE claim_cases SET new_id = gen_random_uuid()")
    op.execute("ALTER TABLE claim_cases ALTER COLUMN new_id SET NOT NULL")

    # 2. For each FK table: add new UUID column, populate, drop old FK
    for table_name, index_name in FK_TABLES:
        # Add new column
        op.add_column(table_name, sa.Column("new_claim_case_id", UUID(as_uuid=True), nullable=True))

        # Populate from claim_cases
        op.execute(
            f"UPDATE {table_name} t SET new_claim_case_id = c.new_id "
            f"FROM claim_cases c WHERE t.claim_case_id = c.id"
        )

        # Drop old foreign key constraint
        constraints = op.get_bind().execute(
            sa.text(
                f"SELECT conname FROM pg_constraint "
                f"WHERE conrelid = '{table_name}'::regclass AND contype = 'f' "
                f"AND confrelid = 'claim_cases'::regclass"
            )
        ).fetchall()
        for (conname,) in constraints:
            op.drop_constraint(conname, table_name, type_="foreignkey")

        # Drop old index if exists
        if index_name:
            op.drop_index(index_name, table_name=table_name)

        # Drop old column, rename new
        op.drop_column(table_name, "claim_case_id")
        op.alter_column(table_name, "new_claim_case_id", new_column_name="claim_case_id", nullable=False)

        # Re-create index
        if index_name:
            op.create_index(index_name, table_name, ["claim_case_id"])

    # 3. Drop old PK on claim_cases, drop old id, rename new_id
    op.execute("ALTER TABLE claim_cases DROP CONSTRAINT claim_cases_pkey")
    op.drop_index("ix_claim_cases_uhid", table_name="claim_cases")
    op.drop_column("claim_cases", "id")
    op.alter_column("claim_cases", "new_id", new_column_name="id")
    op.execute("ALTER TABLE claim_cases ADD PRIMARY KEY (id)")
    op.create_index("ix_claim_cases_uhid", "claim_cases", ["uhid"])

    # 4. Re-create all foreign keys
    for table_name, index_name in FK_TABLES:
        op.create_foreign_key(
            None, table_name, "claim_cases",
            ["claim_case_id"], ["id"],
        )


def downgrade() -> None:
    # This migration is not safely reversible with existing data
    raise NotImplementedError("Downgrade from UUID to BigInteger is not supported")
