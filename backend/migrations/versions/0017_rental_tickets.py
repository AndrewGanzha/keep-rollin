"""Persist tenant-scoped rental issue tickets and private photo links."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_rental_tickets"
down_revision: str | None = "0016_rental_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "ticket",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rental_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="submitted"),
        sa.Column("admin_comment", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("skipped_photo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name="pk_ticket"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_ticket_tenant_id_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "rental_id"],
            ["rental.tenant_id", "rental.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "category IN ('no_power', 'no_drive', 'battery', 'damage', 'other')",
            name=op.f("ck_ticket_category"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(description)) BETWEEN 10 AND 1000",
            name=op.f("ck_ticket_description"),
        ),
        sa.CheckConstraint(
            "status IN ('submitted', 'in_progress', 'resolved')",
            name=op.f("ck_ticket_status"),
        ),
        sa.CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)",
            name=op.f("ck_ticket_resolved_at"),
        ),
        sa.CheckConstraint(
            "status <> 'resolved' OR (admin_comment IS NOT NULL AND btrim(admin_comment) <> '')",
            name=op.f("ck_ticket_resolution_comment"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_ticket_version")),
        sa.CheckConstraint(
            "skipped_photo_count BETWEEN 0 AND 3",
            name=op.f("ck_ticket_skipped_photo_count"),
        ),
    )
    op.create_index("ix_ticket_tenant_created_id", "ticket", ["tenant_id", "created_at", "id"])
    op.create_index(
        "ix_ticket_tenant_rental_created_id",
        "ticket",
        ["tenant_id", "rental_id", "created_at", "id"],
    )

    op.create_table(
        "ticket_attachment",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("ticket_id", "file_id", name="pk_ticket_attachment"),
        sa.UniqueConstraint("ticket_id", "position", name="uq_ticket_attachment_ticket_position"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ticket_id"], ["ticket.tenant_id", "ticket.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["file.tenant_id", "file.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint("position BETWEEN 0 AND 2", name=op.f("ck_ticket_attachment_position")),
    )
    op.create_index(
        "ix_ticket_attachment_tenant_file", "ticket_attachment", ["tenant_id", "file_id"]
    )

    for table, privileges in (
        ("ticket", "SELECT, INSERT, UPDATE"),
        ("ticket_attachment", "SELECT, INSERT"),
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
        )
        op.execute(f"GRANT {privileges} ON {table} TO keep_rollin_app")


def downgrade() -> None:
    # The migration transaction holds this lock and rolls it back on refusal.
    op.execute("ALTER TABLE ticket NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM ticket) THEN
                RAISE EXCEPTION 'cannot downgrade with existing rental tickets';
            END IF;
        END;
        $$;
        """
    )
    op.drop_table("ticket_attachment")
    op.drop_table("ticket")
