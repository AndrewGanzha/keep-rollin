"""Store browser push subscriptions with tenant and owner isolation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_push_subscriptions"
down_revision: str | None = "0021_notification_email_worker"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "push_subscription",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column(
            "version",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("expiration_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_push_subscription"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["user.tenant_id", "user.id"],
            name="fk_push_subscription_tenant_user",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "endpoint", name="uq_push_subscription_tenant_endpoint"),
        sa.CheckConstraint("octet_length(endpoint) BETWEEN 1 AND 2048", name="endpoint_length"),
    )
    op.create_index(
        "ix_push_subscription_active_owner",
        "push_subscription",
        ["tenant_id", "user_id", "created_at", "id"],
        postgresql_where=sa.text("disabled_at IS NULL"),
    )
    op.execute("ALTER TABLE push_subscription ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE push_subscription FORCE ROW LEVEL SECURITY")
    tenant = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        "CREATE POLICY push_subscription_app_tenant ON push_subscription "
        f"TO keep_rollin_app USING ({tenant}) WITH CHECK ({tenant})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON push_subscription TO keep_rollin_app")


def downgrade() -> None:
    op.drop_table("push_subscription")
