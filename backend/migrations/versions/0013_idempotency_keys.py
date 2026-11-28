"""Transaction-scoped per-user idempotency for write endpoints."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_idempotency_keys"
down_revision: str | None = "0012_files_lot_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_key",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", "key", name="pk_idempotency_key"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_idempotency_key_tenant_user",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index("ix_idempotency_key_expires_at", "idempotency_key", ["expires_at"])
    op.execute("ALTER TABLE idempotency_key ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE idempotency_key FORCE ROW LEVEL SECURITY")
    policy = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"CREATE POLICY idempotency_key_tenant ON idempotency_key USING ({policy}) "
        f"WITH CHECK ({policy})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON idempotency_key TO keep_rollin_app")


def downgrade() -> None:
    op.drop_table("idempotency_key")
