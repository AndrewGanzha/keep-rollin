"""Permit the job role to dispatch business email from its tenant outbox."""

import sqlalchemy as sa
from alembic import op

revision: str = "0021_notification_email_worker"
down_revision: str | None = "0020_notification_preferences"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

EMAIL_GRANTS = (
    "SELECT (domain) ON tenant",
    'SELECT (email, notification_preferences) ON "user"',
    "SELECT (id, status, attempts, available_at, last_error, "
    "processed_at, created_at, updated_at) ON outbox_message",
    "UPDATE (status, attempts, available_at, last_error, processed_at, updated_at) "
    "ON outbox_message",
)


def upgrade() -> None:
    for grant in EMAIL_GRANTS:
        op.execute(f"GRANT {grant} TO keep_rollin_worker")
    op.create_index(
        "ix_outbox_message_tenant_pending",
        "outbox_message",
        ["tenant_id", "available_at", "created_at", "id"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_message_tenant_pending", table_name="outbox_message")
    for grant in reversed(EMAIL_GRANTS):
        op.execute(f"REVOKE {grant} FROM keep_rollin_worker")
