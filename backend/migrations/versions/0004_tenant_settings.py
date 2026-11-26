"""Tenant settings for public branding and policies.

Revision ID: 0004_tenant_settings
Revises: 0003_occupancy
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_tenant_settings"
down_revision: str | None = "0003_occupancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = """
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
"""

DEFAULT_POLICIES = (
    '\'{"booking_horizon_days": 60, "min_rental_minutes": 60, '
    '"max_rental_days": 30, "cancellation_free_hours": 24, '
    '"reminder_hours_before": 1, "tickets_per_rental_per_day": 5}\'::jsonb'
)


def upgrade() -> None:
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column(
            "primary_color",
            sa.String(length=7),
            server_default=sa.text("'#0f766e'"),
            nullable=False,
        ),
        sa.Column(
            "policies",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(DEFAULT_POLICIES),
            nullable=False,
        ),
        sa.Column("vapid_public_key", sa.Text(), nullable=True),
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
            ["tenant_id"],
            ["tenant.id"],
            name="fk_tenant_settings_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_tenant_settings"),
    )
    op.execute(
        """
        INSERT INTO tenant_settings (tenant_id)
        SELECT id FROM tenant
        ON CONFLICT (tenant_id) DO NOTHING
        """
    )
    op.execute('ALTER TABLE "tenant_settings" ENABLE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "tenant_settings_tenant_isolation" ON "tenant_settings" '
        f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
    )
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "tenant_settings" TO keep_rollin_app')


def downgrade() -> None:
    op.drop_table("tenant_settings")
