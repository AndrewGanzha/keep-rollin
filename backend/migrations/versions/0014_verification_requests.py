"""Tenant-scoped verification requests with encrypted passport and private document links."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_verification_requests"
down_revision: str | None = "0013_idempotency_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "verification_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passport_enc", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("admin_comment", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id", name="pk_verification_request"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_verification_request_tenant_id_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by"],
            ["user.tenant_id", "user.id"],
            name="fk_verification_request_reviewer_user",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_verification_request_status"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_verification_request_version")),
        sa.CheckConstraint(
            "(status = 'pending' AND reviewed_at IS NULL AND reviewed_by IS NULL "
            "AND admin_comment IS NULL) OR "
            "(status <> 'pending' AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)",
            name=op.f("ck_verification_request_review_state"),
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR (admin_comment IS NOT NULL AND btrim(admin_comment) <> '')",
            name=op.f("ck_verification_request_reject_comment"),
        ),
    )
    op.create_index(
        "uq_verification_request_active_user",
        "verification_request",
        ["tenant_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
    )
    op.create_index(
        "ix_verification_request_tenant_user_created",
        "verification_request",
        ["tenant_id", "user_id", "created_at"],
    )
    op.create_index(
        "ix_verification_request_tenant_created",
        "verification_request",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "verification_document",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("request_id", "purpose", name="pk_verification_document"),
        sa.UniqueConstraint("request_id", "file_id", name="uq_verification_document_request_file"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["verification_request.tenant_id", "verification_request.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["file.tenant_id", "file.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "purpose IN ('verification_passport', 'verification_registration', "
            "'verification_selfie')",
            name=op.f("ck_verification_document_purpose"),
        ),
    )
    op.create_index(
        "ix_verification_document_tenant_file", "verification_document", ["tenant_id", "file_id"]
    )

    for table, privileges in (
        ("verification_request", "SELECT, INSERT, UPDATE"),
        ("verification_document", "SELECT, INSERT"),
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
        )
        op.execute(f"GRANT {privileges} ON {table} TO keep_rollin_app")


def downgrade() -> None:
    op.drop_table("verification_document")
    op.drop_table("verification_request")
