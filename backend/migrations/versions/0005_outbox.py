"""Transactional outbox for notifications and future booking events.

Revision ID: 0005_outbox
Revises: 0004_tenant_settings
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_outbox"
down_revision: str | None = "0004_tenant_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = """
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
"""


def upgrade() -> None:
    op.create_table(
        "outbox_message",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending', 'processing', 'processed', 'failed')",
            name="ck_outbox_message_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_outbox_message_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_message"),
        sa.UniqueConstraint(
            "tenant_id",
            "event_type",
            "entity_id",
            "user_id",
            "channel",
            name="uq_outbox_message_event_chain",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_outbox_message_due",
        "outbox_message",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_outbox_message_tenant_created",
        "outbox_message",
        ["tenant_id", "created_at"],
    )
    op.execute('ALTER TABLE "outbox_message" ENABLE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "outbox_message_tenant_isolation" ON "outbox_message" '
        f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
    )
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "outbox_message" TO keep_rollin_app')


def downgrade() -> None:
    op.drop_table("outbox_message")
