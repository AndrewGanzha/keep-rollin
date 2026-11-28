"""Authentication fields and rotating refresh sessions.

Revision ID: 0006_auth
Revises: 0005_outbox
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_auth"
down_revision: str | None = "0005_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = """
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
"""


def upgrade() -> None:
    op.add_column("user", sa.Column("phone", postgresql.CITEXT(), nullable=True))
    op.add_column("user", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column(
        "user",
        sa.Column(
            "verification_status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
    )
    op.add_column(
        "user",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "user",
        sa.Column(
            "token_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_user_verification_status",
        "user",
        "verification_status IN ('pending', 'approved', 'rejected')",
    )
    op.create_check_constraint("ck_user_token_version", "user", "token_version >= 1")
    op.create_unique_constraint("uq_user_tenant_id_id", "user", ["tenant_id", "id"])

    op.create_table(
        "refresh_session",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
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
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_refresh_session_tenant_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_refresh_session_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_session"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_session_token_hash"),
    )
    op.create_index("ix_refresh_session_family_id", "refresh_session", ["family_id"])
    op.create_index(
        "ix_refresh_session_tenant_user",
        "refresh_session",
        ["tenant_id", "user_id"],
    )
    op.execute('ALTER TABLE "refresh_session" ENABLE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "refresh_session_tenant_isolation" ON "refresh_session" '
        f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
    )
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "refresh_session" TO keep_rollin_app')


def downgrade() -> None:
    op.drop_table("refresh_session")
    op.drop_constraint("uq_user_tenant_id_id", "user", type_="unique")
    op.drop_constraint("ck_user_token_version", "user", type_="check")
    op.drop_constraint("ck_user_verification_status", "user", type_="check")
    op.drop_column("user", "token_version")
    op.drop_column("user", "is_active")
    op.drop_column("user", "verification_status")
    op.drop_column("user", "password_hash")
    op.drop_column("user", "phone")
