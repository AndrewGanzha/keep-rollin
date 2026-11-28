"""Auth hardening: staff MFA challenges and password reset tokens.

Revision ID: 0010_auth_hardening
Revises: 0009_occupancy_admin
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_auth_hardening"
down_revision: str | None = "0009_occupancy_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY = """
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
"""


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "user",
        sa.Column("mfa_secret_enc", sa.Text(), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column("mfa_last_step", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column(
            "mfa_failed_attempts",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "user",
        sa.Column("mfa_failure_window_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column("mfa_locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column(
            "mfa_recovery_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_user_mfa_failed_attempts",
        "user",
        "mfa_failed_attempts BETWEEN 0 AND 5",
    )
    op.create_check_constraint(
        "ck_user_mfa_secret_required",
        "user",
        "mfa_enabled = false OR mfa_secret_enc IS NOT NULL",
    )

    op.create_table(
        "mfa_challenge",
        sa.Column("jti", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("secret_enc", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("purpose IN ('login', 'enroll')", name="ck_mfa_challenge_purpose"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_mfa_challenge_tenant_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("jti", name="pk_mfa_challenge"),
    )
    op.create_index(
        "ix_mfa_challenge_tenant_user_expires",
        "mfa_challenge",
        ["tenant_id", "user_id", "expires_at"],
    )

    op.create_table(
        "password_reset_token",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("token_secret_enc", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_password_reset_token_tenant_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_token"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_token_token_hash"),
    )
    op.create_index(
        "ix_password_reset_token_tenant_user_expires",
        "password_reset_token",
        ["tenant_id", "user_id", "expires_at"],
    )

    op.add_column("tenant_settings", sa.Column("vapid_private_key_enc", sa.Text(), nullable=True))
    op.add_column("tenant_settings", sa.Column("vapid_key_id", sa.Text(), nullable=True))

    for table in ("mfa_challenge", "password_reset_token"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f"USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})"
        )
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO keep_rollin_app')


def downgrade() -> None:
    for table in ("password_reset_token", "mfa_challenge"):
        op.drop_table(table)

    op.drop_column("tenant_settings", "vapid_key_id")
    op.drop_column("tenant_settings", "vapid_private_key_enc")

    op.drop_constraint("ck_user_mfa_secret_required", "user", type_="check")
    op.drop_constraint("ck_user_mfa_failed_attempts", "user", type_="check")
    op.drop_column("user", "mfa_recovery_hashes")
    op.drop_column("user", "mfa_locked_until")
    op.drop_column("user", "mfa_failure_window_started_at")
    op.drop_column("user", "mfa_failed_attempts")
    op.drop_column("user", "mfa_last_step")
    op.drop_column("user", "mfa_secret_enc")
    op.drop_column("user", "mfa_enabled")
