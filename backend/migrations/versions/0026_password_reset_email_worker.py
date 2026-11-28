"""Allow the SMTP worker to read encrypted password-reset delivery material."""

from alembic import op

revision: str = "0026_password_reset_email_worker"
down_revision: str | None = "0025_analytics_read_indexes"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

DELIVERY_COLUMNS = (
    "SELECT (id, tenant_id, user_id, token_secret_enc, expires_at, consumed_at) "
    "ON password_reset_token"
)


def upgrade() -> None:
    op.execute(f"GRANT {DELIVERY_COLUMNS} TO keep_rollin_worker")


def downgrade() -> None:
    op.execute(f"REVOKE {DELIVERY_COLUMNS} FROM keep_rollin_worker")
