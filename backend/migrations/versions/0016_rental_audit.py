"""Record rental and stock changes in the transactional audit log."""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_rental_audit"
down_revision: str | None = "0015_rentals_and_battery_stock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTIONS = (
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
    "rental.closed",
    "rental.overdue",
    "ticket.status_changed",
)
OLD_ENTITIES = (
    "tenant",
    "user",
    "tenant_settings",
    "category",
    "offer",
    "lot",
    "lot_block",
    "verification_request",
    "rental",
    "ticket",
)
ADDED_ACTIONS = (
    "rental.booked",
    "rental.cancelled",
    "battery_stock.created",
    "battery_stock.updated",
    "battery_stock.deleted",
)

ACTOR_RULE = (
    "(actor_role IN ({roles}) AND actor_id IS NOT NULL) OR "
    "(actor_role IN ('system', 'platform') AND actor_id IS NULL)"
)


def _replace_constraints(*, expanded: bool) -> None:
    actions = OLD_ACTIONS + ADDED_ACTIONS if expanded else OLD_ACTIONS
    entities = (*OLD_ENTITIES, "battery_stock") if expanded else OLD_ENTITIES
    roles = "'owner', 'admin', 'user'" if expanded else "'owner', 'admin'"
    predicates = {
        "action": f"action IN ({', '.join(map(repr, actions))})",
        "entity_type": f"entity_type IN ({', '.join(map(repr, entities))})",
        "actor_role": f"actor_role IN ({roles}, 'system', 'platform')",
        "actor": ACTOR_RULE.format(roles=roles),
    }
    # Preserve historical events when rolling back. PostgreSQL still enforces the
    # previous allowlist for new writes, and a subsequent upgrade validates all rows.
    validation = "" if expanded else " NOT VALID"
    for name, predicate in predicates.items():
        constraint = f"ck_audit_log_{name}"
        legacy = f"ck_audit_log_{constraint}"
        previous = legacy if expanded else constraint
        replacement = constraint if expanded else legacy
        op.drop_constraint(op.f(previous), "audit_log", type_="check")
        op.execute(
            f"ALTER TABLE audit_log ADD CONSTRAINT {replacement} CHECK ({predicate}){validation}"
        )


def upgrade() -> None:
    _replace_constraints(expanded=True)
    op.create_check_constraint(
        op.f("ck_audit_log_user_action"),
        "audit_log",
        "actor_role <> 'user' OR (entity_type = 'rental' "
        "AND action IN ('rental.booked', 'rental.cancelled'))",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_audit_log_user_action"), "audit_log", type_="check")
    _replace_constraints(expanded=False)
