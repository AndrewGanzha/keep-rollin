"""Per-tenant uploaded files and ordered lot attachments."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_files_lot_attachments"
down_revision: str | None = "0011_admin_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "file",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("object_key", sa.String(128), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.Column("is_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_purging", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_file"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_file_tenant_id_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "uploaded_by"], ["user.tenant_id", "user.id"]),
        sa.CheckConstraint(
            "purpose IN ('lot_photo', 'ticket_photo', 'verification_passport', "
            "'verification_registration', 'verification_selfie')",
            name="ck_file_purpose",
        ),
        sa.CheckConstraint(
            "(purpose = 'lot_photo') = (public_url IS NOT NULL)",
            name="ck_file_public_purpose",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_file_size_bytes"),
        sa.CheckConstraint("NOT (is_ready AND is_purging)", name="ck_file_state"),
    )
    op.create_index("ix_file_created_id", "file", ["created_at", "id"])
    op.create_table(
        "attachment",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("lot_id", "file_id", name="pk_attachment"),
        sa.UniqueConstraint("lot_id", "position", name="uq_attachment_lot_position"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lot_id"], ["lot.tenant_id", "lot.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id", "file_id"], ["file.tenant_id", "file.id"]),
        sa.CheckConstraint("position >= 0", name="ck_attachment_position"),
    )
    op.create_index("ix_attachment_tenant_file", "attachment", ["tenant_id", "file_id"])

    for table in ("file", "attachment"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY {table}_tenant ON "{table}" '
            f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
        )
    op.execute('GRANT SELECT, INSERT, UPDATE ON "file" TO keep_rollin_app')
    op.execute("GRANT SELECT, INSERT, DELETE ON attachment TO keep_rollin_app")


def downgrade() -> None:
    op.drop_table("attachment")
    op.drop_table("file")
