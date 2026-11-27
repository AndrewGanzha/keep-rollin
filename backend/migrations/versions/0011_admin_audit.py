"""Audit log and admin listing indexes.

Revision ID: 0011_admin_audit
Revises: 0010_auth_hardening
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_admin_audit"
down_revision: str | None = "0010_auth_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = """
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
"""

AUDIT_ACTIONS = (
    "tenant.provisioned",
    "admin.created",
    "admin.deactivated",
    "user.deactivated",
    "settings.updated",
    "category.created",
    "category.updated",
    "category.characteristics_updated",
    "offer.created",
    "offer.updated",
    "offer.published",
    "lot.blocked",
    "lot.unblocked",
    "lot.status_changed",
    "verification.decided",
    "rental.closed",
    "rental.overdue",
    "ticket.status_changed",
)

ENTITY_TYPES = (
    "tenant",
    "user",
    "tenant_settings",
    "category",
    "offer",
    "lot",
    "lot_block",
    "verification_request",
    "rental",
    "ticket",
)


def upgrade() -> None:
    op.create_index(
        "ix_user_tenant_created_id",
        "user",
        ["tenant_id", "created_at", "id"],
    )
    op.create_index(
        "ix_user_tenant_role_created_id",
        "user",
        ["tenant_id", "role", "created_at", "id"],
    )

    action_list = ", ".join(f"'{action}'" for action in AUDIT_ACTIONS)
    entity_list = ", ".join(f"'{entity}'" for entity in ENTITY_TYPES)
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(length=16), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"action IN ({action_list})", name="ck_audit_log_action"),
        sa.CheckConstraint(
            f"entity_type IN ({entity_list})",
            name="ck_audit_log_entity_type",
        ),
        sa.CheckConstraint(
            "actor_role IN ('owner', 'admin', 'system', 'platform')",
            name="ck_audit_log_actor_role",
        ),
        sa.CheckConstraint(
            "(actor_role IN ('owner', 'admin') AND actor_id IS NOT NULL) "
            "OR (actor_role IN ('system', 'platform') AND actor_id IS NULL)",
            name="ck_audit_log_actor",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object' AND pg_column_size(metadata) <= 4096",
            name="ck_audit_log_metadata",
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR char_length(request_id) BETWEEN 1 AND 128",
            name="ck_audit_log_request_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["user.tenant_id", "user.id"],
            name="fk_audit_log_tenant_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_audit_log_tenant_id_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index(
        "ix_audit_log_tenant_created_id",
        "audit_log",
        ["tenant_id", "created_at", "id"],
    )
    op.create_index(
        "ix_audit_log_tenant_actor_created_id",
        "audit_log",
        ["tenant_id", "actor_id", "created_at", "id"],
        postgresql_where=sa.text("actor_id IS NOT NULL"),
    )
    op.create_index(
        "ix_audit_log_tenant_action_created_id",
        "audit_log",
        ["tenant_id", "action", "created_at", "id"],
    )
    op.create_index(
        "ix_audit_log_tenant_entity_created_id",
        "audit_log",
        ["tenant_id", "entity_type", "entity_id", "created_at", "id"],
        postgresql_where=sa.text("entity_id IS NOT NULL"),
    )
    op.create_index("ix_audit_log_created_id", "audit_log", ["created_at", "id"])

    op.execute('ALTER TABLE "audit_log" ENABLE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "audit_log_tenant_isolation" ON "audit_log" '
        f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
    )
    op.execute('GRANT SELECT, INSERT ON "audit_log" TO keep_rollin_app')
    op.execute('REVOKE UPDATE, DELETE, TRUNCATE ON "audit_log" FROM keep_rollin_app')


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_index("ix_user_tenant_role_created_id", table_name="user")
    op.drop_index("ix_user_tenant_created_id", table_name="user")
