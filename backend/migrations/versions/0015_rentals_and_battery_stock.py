"""Tenant-isolated rentals and shared battery stock."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_rentals_and_battery_stock"
down_revision: str | None = "0014_verification_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_occupancy_tenant_lot_id", "occupancy", ["tenant_id", "lot_id", "id"]
    )
    op.create_table(
        "battery_stock",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.func.gen_random_uuid(),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("battery_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_battery_stock"),
        sa.UniqueConstraint("tenant_id", "battery_type", name="uq_battery_stock_tenant_type"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.CheckConstraint("btrim(battery_type) <> ''", name=op.f("ck_battery_stock_battery_type")),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_battery_stock_name")),
        sa.CheckConstraint("quantity >= 0", name=op.f("ck_battery_stock_quantity")),
    )
    op.create_table(
        "rental",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occupancy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("battery_type", sa.Text()),
        sa.Column("battery_count", sa.BigInteger(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_minor", sa.Numeric(24, 0), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="booked"),
        sa.Column("cancellation_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by", postgresql.UUID(as_uuid=True)),
        sa.Column("cancellation_reason", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("close_comment", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rental"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_rental_tenant_id_id"),
        sa.UniqueConstraint("occupancy_id", name="uq_rental_occupancy"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_rental_tenant_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lot_id"],
            ["lot.tenant_id", "lot.id"],
            name="fk_rental_tenant_lot",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lot_id", "occupancy_id"],
            ["occupancy.tenant_id", "occupancy.lot_id", "occupancy.id"],
            name="fk_rental_tenant_lot_occupancy",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "battery_type"],
            ["battery_stock.tenant_id", "battery_stock.battery_type"],
            name="fk_rental_tenant_battery_stock",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "closed_by"],
            ["user.tenant_id", "user.id"],
            name="fk_rental_tenant_closed_by_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "cancelled_by"],
            ["user.tenant_id", "user.id"],
            name="fk_rental_tenant_cancelled_by_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "status IN ('booked', 'active', 'overdue', 'completed', 'cancelled')",
            name=op.f("ck_rental_status"),
        ),
        sa.CheckConstraint("start_time < end_time", name=op.f("ck_rental_period")),
        sa.CheckConstraint("price_minor > 0", name=op.f("ck_rental_price_minor")),
        sa.CheckConstraint(
            "(battery_count = 0 AND battery_type IS NULL) OR "
            "(battery_count > 0 AND battery_type IS NOT NULL)",
            name=op.f("ck_rental_battery"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_rental_version")),
    )
    op.create_index("ix_rental_tenant_created", "rental", ["tenant_id", "created_at", "id"])
    op.create_index(
        "ix_rental_tenant_user_created", "rental", ["tenant_id", "user_id", "created_at", "id"]
    )
    op.create_index("ix_rental_tenant_lot", "rental", ["tenant_id", "lot_id"])
    op.create_index(
        "ix_rental_tenant_battery_end", "rental", ["tenant_id", "battery_type", "end_time"]
    )

    for table, privileges in (
        ("battery_stock", "SELECT, INSERT, UPDATE, DELETE"),
        ("rental", "SELECT, INSERT, UPDATE"),
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
        )
        op.execute(f"GRANT {privileges} ON {table} TO keep_rollin_app")


def downgrade() -> None:
    # Hold out writers until the downgrade transaction commits. Never leave live
    # occupancy references behind or discard rental and stock data silently.
    op.execute("LOCK TABLE rental, battery_stock IN ACCESS EXCLUSIVE MODE")
    op.execute("SET LOCAL row_security = off")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM rental) OR EXISTS (SELECT 1 FROM battery_stock) THEN
                RAISE EXCEPTION 'cannot downgrade with existing rentals or battery stock';
            END IF;
        END;
        $$;
        """
    )
    op.execute("SET LOCAL row_security = on")
    op.drop_table("rental")
    op.drop_table("battery_stock")
    op.drop_constraint("uq_occupancy_tenant_lot_id", "occupancy", type_="unique")
