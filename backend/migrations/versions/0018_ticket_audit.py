"""Allow audited creation of ticket records by their renter."""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_ticket_audit"
down_revision: str | None = "0017_rental_tickets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIOUS_ACTIONS = (
    "tenant.provisioned",
    "admin.created",
    "admin.deactivated",
    "user.deactivated",
    "settings.updated",
    "category.created",
    "category.updated",
    "category.characteristics_updated",
    "offer.created",
    "offer.updated",
    "offer.published",
    "lot.blocked",
    "lot.unblocked",
    "lot.status_changed",
    "verification.decided",
    "rental.booked",
    "rental.cancelled",
    "battery_stock.created",
    "battery_stock.updated",
    "battery_stock.deleted",
    "rental.closed",
    "rental.overdue",
    "ticket.status_changed",
)

PREVIOUS_USER_RULE = (
    "actor_role <> 'user' OR (entity_type = 'rental' "
    "AND action IN ('rental.booked', 'rental.cancelled'))"
)
TICKET_USER_RULE = " OR (entity_type = 'ticket' AND action = 'ticket.created')"


def _replace_constraints(*, enable_ticket: bool) -> None:
    actions = (*PREVIOUS_ACTIONS, "ticket.created") if enable_ticket else PREVIOUS_ACTIONS
    user_rule = PREVIOUS_USER_RULE + TICKET_USER_RULE if enable_ticket else PREVIOUS_USER_RULE
    definitions = {
        "ck_audit_log_action": f"action IN ({', '.join(map(repr, actions))})",
        "ck_audit_log_user_action": user_rule,
    }
    for name, predicate in definitions.items():
        op.drop_constraint(op.f(name), "audit_log", type_="check")
        op.execute(f"ALTER TABLE audit_log ADD CONSTRAINT {name} CHECK ({predicate})")


def upgrade() -> None:
    _replace_constraints(enable_ticket=True)


def downgrade() -> None:
    # The migration transaction holds this lock and rolls it back on refusal.
    op.execute("ALTER TABLE audit_log NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM audit_log WHERE action = 'ticket.created') THEN
                RAISE EXCEPTION 'cannot downgrade with existing ticket audit history';
            END IF;
        END;
        $$;
        """
    )
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    _replace_constraints(enable_ticket=False)
