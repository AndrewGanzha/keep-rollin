"""Occupancy intervals with tenant-safe exclusion.

Revision ID: 0003_occupancy
Revises: 0002_catalog
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_occupancy"
down_revision: str | None = "0002_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = """
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
"""


def upgrade() -> None:
    op.create_table(
        "occupancy",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("period", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("ref_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('booking', 'block', 'maintenance')",
            name="ck_occupancy_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'released')",
            name="ck_occupancy_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lot_id"],
            ["lot.tenant_id", "lot.id"],
            name="fk_occupancy_tenant_lot",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_occupancy_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_occupancy"),
    )
    op.create_index("ix_occupancy_tenant_lot", "occupancy", ["tenant_id", "lot_id"])
    op.execute(
        "ALTER TABLE occupancy "
        "ADD CONSTRAINT ex_occupancy_no_overlap "
        "EXCLUDE USING gist (tenant_id WITH =, lot_id WITH =, period WITH &&) "
        "WHERE (status = 'active')"
    )
    op.execute('ALTER TABLE "occupancy" ENABLE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "occupancy_tenant_isolation" ON "occupancy" '
        f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
    )
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "occupancy" TO keep_rollin_app')


def downgrade() -> None:
    op.drop_table("occupancy")
