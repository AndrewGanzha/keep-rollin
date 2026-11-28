"""Give the delivery worker access to Web Push subscriptions and encrypted VAPID keys."""

from alembic import op

revision: str = "0023_push_worker_grants"
down_revision: str | None = "0022_push_subscriptions"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

TENANT = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

GRANTS = (
    "SELECT (id, tenant_id, user_id, endpoint, p256dh, auth, version, "
    "expiration_time, created_at, disabled_at) ON push_subscription",
    "UPDATE (disabled_at) ON push_subscription",
    "SELECT (tenant_id, vapid_private_key_enc) ON tenant_settings",
)


def upgrade() -> None:
    op.execute(
        "CREATE POLICY push_subscription_worker_read ON push_subscription "
        f"FOR SELECT TO keep_rollin_worker USING ({TENANT})"
    )
    op.execute(
        "CREATE POLICY push_subscription_worker_invalidate ON push_subscription "
        f"FOR UPDATE TO keep_rollin_worker USING ({TENANT} AND disabled_at IS NULL) "
        f"WITH CHECK ({TENANT} AND disabled_at IS NOT NULL)"
    )
    for grant in GRANTS:
        op.execute(f"GRANT {grant} TO keep_rollin_worker")


def downgrade() -> None:
    for grant in reversed(GRANTS):
        op.execute(f"REVOKE {grant} FROM keep_rollin_worker")
    op.execute("DROP POLICY push_subscription_worker_invalidate ON push_subscription")
    op.execute("DROP POLICY push_subscription_worker_read ON push_subscription")
