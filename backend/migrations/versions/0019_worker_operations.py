"""Least-privilege worker and indexes for due jobs."""

import sqlalchemy as sa
from alembic import op

revision: str = "0019_worker_operations"
down_revision: str | None = "0018_ticket_audit"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

WORKER_GRANTS = (
    "USAGE ON SCHEMA public",
    "SELECT (id, is_active) ON tenant",
    'SELECT (id, tenant_id, role, is_active) ON "user"',
    "SELECT (tenant_id, id, lot_id, user_id, status, start_time, end_time, version) ON rental",
    "SELECT (tenant_id, id, status, version) ON lot",
    "SELECT (tenant_id, id, lot_id, kind, status, period, ref_id, created_by, reason, "
    "created_at) ON occupancy",
    "UPDATE (status, version, updated_at) ON rental, lot",
    "UPDATE (status, updated_at) ON occupancy",
    "INSERT ON audit_log, outbox_message",
    "SELECT (tenant_id, event_type, entity_id, user_id, channel) ON outbox_message",
    "SELECT (tenant_id, user_id, key, expires_at), DELETE ON idempotency_key",
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'keep_rollin_worker') THEN
                CREATE ROLE keep_rollin_worker NOLOGIN NOINHERIT;
            END IF;
            IF EXISTS (
                SELECT FROM pg_roles
                WHERE rolname = 'keep_rollin_worker'
                  AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication)
            ) THEN
                RAISE EXCEPTION 'keep_rollin_worker must be a restricted role';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "CREATE POLICY worker_active_tenants ON tenant "
        "FOR SELECT TO keep_rollin_worker USING (is_active)"
    )
    for grant in WORKER_GRANTS:
        op.execute(f"GRANT {grant} TO keep_rollin_worker")

    op.create_index(
        "ix_rental_worker_booked_start",
        "rental",
        ["tenant_id", "start_time", "id"],
        postgresql_where=sa.text("status = 'booked'"),
    )
    op.create_index(
        "ix_rental_worker_active_end",
        "rental",
        ["tenant_id", "end_time", "id"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_idempotency_key_tenant_expiry",
        "idempotency_key",
        ["tenant_id", "expires_at", "user_id", "key"],
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_key_tenant_expiry", table_name="idempotency_key")
    op.drop_index("ix_rental_worker_active_end", table_name="rental")
    op.drop_index("ix_rental_worker_booked_start", table_name="rental")
    for grant in reversed(WORKER_GRANTS):
        op.execute(f"REVOKE {grant} FROM keep_rollin_worker")
    op.execute("DROP POLICY worker_active_tenants ON tenant")
