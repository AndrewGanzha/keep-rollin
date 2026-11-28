"""Indexes for analytics rental starts, overlap utilization, and catalog groups."""

import sqlalchemy as sa
from alembic import op

revision: str = "0025_analytics_read_indexes"
down_revision: str | None = "0024_rental_reminder_worker"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_rental_analytics_start",
        "rental",
        ["tenant_id", "start_time", "id"],
        postgresql_include=["lot_id", "end_time", "status", "price_minor"],
    )
    op.create_index(
        "ix_rental_analytics_lot_start",
        "rental",
        ["tenant_id", "lot_id", "start_time", "id"],
    )
    op.create_index(
        "ix_rental_analytics_usage",
        "rental",
        ["tenant_id", "lot_id", sa.text("tstzrange(start_time, end_time, '[)')")],
        postgresql_using="gist",
        postgresql_where=sa.text("status IN ('active', 'overdue', 'completed')"),
    )
    op.create_index("ix_lot_analytics_category", "lot", ["tenant_id", "category_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_lot_analytics_category", table_name="lot")
    op.drop_index("ix_rental_analytics_usage", table_name="rental")
    op.drop_index("ix_rental_analytics_lot_start", table_name="rental")
    op.drop_index("ix_rental_analytics_start", table_name="rental")
