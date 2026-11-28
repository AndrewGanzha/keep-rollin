"""Tenant settings version, offers and acceptances.

Revision ID: 0008_admin_content
Revises: 0007_category_version
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_admin_content"
down_revision: str | None = "0007_category_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = """
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
"""

DEFAULT_POLICIES = (
    '\'{"booking_horizon_days": 60, "min_rental_minutes": 60, '
    '"max_rental_days": 30, "cancellation_free_hours": 24, '
    '"reminder_hours_before": 1, "tickets_per_rental_per_day": 5, '
    '"lot_photos_max": 10, "verification_docs_retention_days": 90}\'::jsonb'
)
OLD_DEFAULT_POLICIES = (
    '\'{"booking_horizon_days": 60, "min_rental_minutes": 60, '
    '"max_rental_days": 30, "cancellation_free_hours": 24, '
    '"reminder_hours_before": 1, "tickets_per_rental_per_day": 5}\'::jsonb'
)


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_check_constraint("ck_tenant_settings_version", "tenant_settings", "version >= 1")
    op.execute(
        f'ALTER TABLE "tenant_settings" ALTER COLUMN "policies" SET DEFAULT {DEFAULT_POLICIES}'
    )

    op.create_table(
        "offer_version",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("version >= 1", name="ck_offer_version_positive"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_offer_version_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_offer_version_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_offer_version"),
        sa.UniqueConstraint("tenant_id", "version", name="uq_offer_version_tenant_version"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_offer_version_tenant_id_id"),
    )
    op.create_index("ix_offer_version_tenant_id", "offer_version", ["tenant_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_offer_version_one_active "
        "ON offer_version (tenant_id) WHERE status = 'active'"
    )

    op.create_table(
        "offer_acceptance",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offer_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_offer_acceptance_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_offer_acceptance_tenant_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "offer_version_id"],
            ["offer_version.tenant_id", "offer_version.id"],
            name="fk_offer_acceptance_tenant_offer",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_offer_acceptance"),
        sa.UniqueConstraint(
            "user_id",
            "offer_version_id",
            name="uq_offer_acceptance_user_version",
        ),
    )
    op.create_index(
        "ix_offer_acceptance_tenant_user",
        "offer_acceptance",
        ["tenant_id", "user_id"],
    )
    op.create_index(
        "ix_offer_acceptance_offer_version",
        "offer_acceptance",
        ["offer_version_id"],
    )

    for table in ("offer_version", "offer_acceptance"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
        )
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO keep_rollin_app')


def downgrade() -> None:
    op.drop_table("offer_acceptance")
    op.drop_table("offer_version")
    op.execute(
        f'ALTER TABLE "tenant_settings" ALTER COLUMN "policies" SET DEFAULT {OLD_DEFAULT_POLICIES}'
    )
    op.drop_constraint("ck_tenant_settings_version", "tenant_settings", type_="check")
    op.drop_column("tenant_settings", "version")
