"""Catalog categories, characteristics, lots, variants and price tiers.

Revision ID: 0002_catalog
Revises: 0001_initial
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_catalog"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = """
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
"""


def upgrade() -> None:
    op.create_table(
        "category",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_category_tenant_id_tenant", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_category"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_category_tenant_slug"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_category_tenant_id_id"),
    )
    op.create_index("ix_category_tenant_id", "category", ["tenant_id"], unique=False)

    op.create_table(
        "characteristic",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", postgresql.CITEXT(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("sort", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.CheckConstraint("type IN ('number', 'text', 'select')", name="ck_characteristic_type"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["category.tenant_id", "category.id"],
            name="fk_characteristic_tenant_category",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_characteristic_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_characteristic"),
        sa.UniqueConstraint("category_id", "code", name="uq_characteristic_category_code"),
    )
    op.create_index("ix_characteristic_category_id", "characteristic", ["category_id"])
    op.create_index("ix_characteristic_tenant_id", "characteristic", ["tenant_id"])

    op.create_table(
        "lot",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "photos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "characteristics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("rental_unit", sa.Text(), nullable=False),
        sa.Column("battery_type", sa.Text(), nullable=True),
        sa.Column("allowed_durations", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
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
        sa.CheckConstraint("rental_unit IN ('day', 'hour')", name="ck_lot_rental_unit"),
        sa.CheckConstraint(
            "status IN ('active', 'archived', 'maintenance', 'overdue')",
            name="ck_lot_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["category.tenant_id", "category.id"],
            name="fk_lot_tenant_category",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_lot_tenant_id_tenant", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lot"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_lot_tenant_slug"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_lot_tenant_id_id"),
    )
    op.create_index("ix_lot_tenant_id", "lot", ["tenant_id"])
    op.create_index("ix_lot_category_id", "lot", ["category_id"])
    op.create_index("ix_lot_status", "lot", ["status"])

    op.create_table(
        "lot_variant",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("battery_count", sa.BigInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.CheckConstraint("battery_count >= 0", name="ck_lot_variant_battery_count"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lot_id"],
            ["lot.tenant_id", "lot.id"],
            name="fk_lot_variant_tenant_lot",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_lot_variant_tenant_id_tenant", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lot_variant"),
        sa.UniqueConstraint("lot_id", "battery_count", name="uq_lot_variant_battery"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_lot_variant_tenant_id_id"),
    )
    op.create_index("ix_lot_variant_lot_id", "lot_variant", ["lot_id"])
    op.create_index("ix_lot_variant_tenant_id", "lot_variant", ["tenant_id"])

    op.create_table(
        "lot_price_tier",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("min_units", sa.BigInteger(), nullable=False),
        sa.Column("price_per_unit_minor", sa.BigInteger(), nullable=False),
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
        sa.CheckConstraint("min_units >= 1", name="ck_lot_price_tier_min_units"),
        sa.CheckConstraint("price_per_unit_minor >= 1", name="ck_lot_price_tier_price"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["lot_variant.tenant_id", "lot_variant.id"],
            name="fk_lot_price_tier_tenant_variant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_lot_price_tier_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lot_price_tier"),
        sa.UniqueConstraint("variant_id", "min_units", name="uq_lot_price_tier_variant_min"),
    )
    op.create_index("ix_lot_price_tier_variant_id", "lot_price_tier", ["variant_id"])
    op.create_index("ix_lot_price_tier_tenant_id", "lot_price_tier", ["tenant_id"])

    for table in ("category", "characteristic", "lot", "lot_variant", "lot_price_tier"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
        )
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO keep_rollin_app')


def downgrade() -> None:
    for table in ("lot_price_tier", "lot_variant", "lot", "characteristic", "category"):
        op.drop_table(table)
