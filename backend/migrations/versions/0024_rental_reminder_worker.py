"""Let the worker read the tenant's configured rental reminder window."""

from alembic import op

revision: str = "0024_rental_reminder_worker"
down_revision: str | None = "0023_push_worker_grants"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("GRANT SELECT (policies) ON tenant_settings TO keep_rollin_worker")


def downgrade() -> None:
    op.execute("REVOKE SELECT (policies) ON tenant_settings FROM keep_rollin_worker")
