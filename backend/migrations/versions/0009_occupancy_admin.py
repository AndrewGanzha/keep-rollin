"""Occupancy admin metadata for calendar blocks.

Revision ID: 0009_occupancy_admin
Revises: 0008_admin_content
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_occupancy_admin"
down_revision: str | None = "0008_admin_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("occupancy", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column(
        "occupancy",
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_occupancy_reason_length",
        "occupancy",
        "reason IS NULL OR char_length(reason) BETWEEN 3 AND 200",
    )
    op.create_foreign_key(
        "fk_occupancy_tenant_created_by_user",
        "occupancy",
        "user",
        ["tenant_id", "created_by"],
        ["tenant_id", "id"],
    )
    op.create_index(
        "ix_occupancy_tenant_created_by",
        "occupancy",
        ["tenant_id", "created_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_occupancy_tenant_created_by", table_name="occupancy")
    op.drop_constraint("fk_occupancy_tenant_created_by_user", "occupancy", type_="foreignkey")
    op.drop_constraint("ck_occupancy_reason_length", "occupancy", type_="check")
    op.drop_column("occupancy", "created_by")
    op.drop_column("occupancy", "reason")
