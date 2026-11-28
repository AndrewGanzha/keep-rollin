from __future__ import annotations

import contextlib
import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from src.domain.value_objects.limits import MAX_DATABASE_INTEGER

ALLOWED_ACTIONS = frozenset(
    {
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
        "ticket.created",
        "ticket.status_changed",
    }
)
ALLOWED_ENTITY_TYPES = frozenset(
    {
        "tenant",
        "user",
        "tenant_settings",
        "category",
        "offer",
        "lot",
        "lot_block",
        "verification_request",
        "rental",
        "battery_stock",
        "ticket",
    }
)
ALLOWED_ROLES = frozenset({"owner", "admin", "user", "system", "platform"})
ACTION_METADATA_KEYS: dict[str, frozenset[str]] = {
    "tenant.provisioned": frozenset({"source"}),
    "admin.created": frozenset({"role"}),
    "admin.deactivated": frozenset({"role"}),
    "user.deactivated": frozenset({"role"}),
    "settings.updated": frozenset({"changed_fields"}),
    "category.created": frozenset({"is_archived"}),
    "category.updated": frozenset({"changed_fields", "is_archived"}),
    "category.characteristics_updated": frozenset({"count"}),
    "offer.created": frozenset({"version"}),
    "offer.updated": frozenset({"version"}),
    "offer.published": frozenset({"version"}),
    "lot.status_changed": frozenset({"old_status", "new_status"}),
    "ticket.status_changed": frozenset({"old_status", "new_status"}),
    "verification.decided": frozenset({"decision"}),
    "rental.closed": frozenset({"lot_status"}),
}
METADATA_MAX_KEYS = 10
METADATA_MAX_BYTES = 4096


class AuditError(Exception):
    pass


@dataclass(frozen=True)
class AuditEntry:
    id: UUID
    tenant_id: UUID
    action: str
    actor_id: UUID | None
    actor_role: str
    ip: str | None
    entity_type: str
    entity_id: UUID | None
    metadata: dict[str, object]
    request_id: str | None
    created_at: datetime


class AuditRepositoryPort(Protocol):
    async def add(self, entry: AuditEntry) -> None: ...

    async def list_entries(
        self,
        *,
        actor_id: UUID | None,
        action: str | None,
        entity_type: str | None,
        entity_id: UUID | None,
        from_at: datetime | None,
        to_at: datetime | None,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[AuditEntry]: ...

    async def purge_before(self, *, cutoff: datetime, batch_size: int) -> int: ...


class AuditWriter:
    def __init__(self, repository: AuditRepositoryPort, *, tenant_id: UUID) -> None:
        self._repository = repository
        self._tenant_id = tenant_id

    async def record(
        self,
        *,
        action: str,
        actor_id: UUID | None,
        actor_role: str,
        entity_type: str,
        entity_id: UUID | None = None,
        metadata: dict[str, object] | None = None,
        ip: str | None = None,
        request_id: str | None = None,
        created_at: datetime | None = None,
    ) -> AuditEntry:
        validate_audit_event(
            action=action,
            actor_id=actor_id,
            actor_role=actor_role,
            entity_type=entity_type,
            metadata=metadata or {},
            ip=ip,
            request_id=request_id,
        )
        now = created_at or datetime.now(tz=UTC)
        entry = AuditEntry(
            id=uuid4(),
            tenant_id=self._tenant_id,
            action=action,
            actor_id=actor_id,
            actor_role=actor_role,
            ip=_valid_ip(ip),
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=dict(metadata or {}),
            request_id=request_id,
            created_at=now,
        )
        await self._repository.add(entry)
        return entry


def validate_audit_event(
    *,
    action: str,
    actor_id: UUID | None,
    actor_role: str,
    entity_type: str,
    metadata: dict[str, object],
    ip: str | None,
    request_id: str | None,
) -> None:
    if action not in ALLOWED_ACTIONS:
        raise AuditError("unknown audit action")
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise AuditError("unknown audit entity type")
    if actor_role not in ALLOWED_ROLES:
        raise AuditError("invalid audit actor role")
    if actor_role in ("owner", "admin", "user") and actor_id is None:
        raise AuditError("account audit requires an actor id")
    if actor_role == "user" and (action, entity_type) not in {
        ("rental.booked", "rental"),
        ("rental.cancelled", "rental"),
        ("ticket.created", "ticket"),
    }:
        raise AuditError("invalid audit action for a user actor")
    if actor_role in ("system", "platform") and actor_id is not None:
        raise AuditError("system audit must not have an actor id")
    if len(metadata) > METADATA_MAX_KEYS:
        raise AuditError("audit metadata has too many keys")
    allowed = ACTION_METADATA_KEYS.get(action, frozenset())
    unknown = set(metadata) - allowed
    if unknown:
        raise AuditError("audit metadata contains unsupported fields")
    for key, value in metadata.items():
        _validate_metadata_value(action, key, value)
    if ip is not None:
        with contextlib.suppress(ValueError):
            # Test clients and misconfigured proxies can expose a non-IP host;
            # audit must not fail the business operation for that.
            ipaddress.ip_address(ip)
    if request_id is not None and not 1 <= len(request_id) <= 128:
        raise AuditError("invalid audit request id")
    if len(str(metadata).encode("utf-8")) > METADATA_MAX_BYTES:
        raise AuditError("audit metadata is too large")


CHANGED_FIELD_NAMES = frozenset(
    {
        "name",
        "slug",
        "description",
        "primary_color",
        "logo_url",
        "policies",
        "timezone",
        "currency",
        "booking_horizon_days",
        "min_rental_minutes",
        "max_rental_days",
        "cancellation_free_hours",
        "reminder_hours_before",
        "tickets_per_rental_per_day",
        "lot_photos_max",
        "verification_docs_retention_days",
        "title",
        "body",
        "price_minor",
        "model",
        "status",
        "category_id",
        "characteristics",
        "photos",
        "sort",
        "code",
        "type",
        "unit",
        "is_required",
        "options",
        "is_archived",
    }
)
ACTION_STATUS_VALUES: dict[tuple[str, str], frozenset[str]] = {
    ("ticket.status_changed", "old_status"): frozenset({"submitted", "in_progress", "resolved"}),
    ("ticket.status_changed", "new_status"): frozenset({"submitted", "in_progress", "resolved"}),
    ("lot.status_changed", "old_status"): frozenset(
        {"active", "archived", "maintenance", "overdue"}
    ),
    ("lot.status_changed", "new_status"): frozenset(
        {"active", "archived", "maintenance", "overdue"}
    ),
    ("rental.closed", "lot_status"): frozenset({"active", "archived", "maintenance", "overdue"}),
    ("verification.decided", "decision"): frozenset({"approved", "rejected"}),
}


def _valid_ip(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def _validate_metadata_value(action: str, key: str, value: object) -> None:
    if key == "role":
        if value not in ("owner", "admin", "user"):
            raise AuditError("invalid audit role metadata")
        return
    if key == "source":
        if value != "cli":
            raise AuditError("invalid audit source metadata")
        return
    if key in ("old_status", "new_status", "lot_status", "decision"):
        allowed = ACTION_STATUS_VALUES.get((action, key), frozenset())
        if value not in allowed:
            raise AuditError("invalid audit status metadata")
        return
    if key == "is_archived":
        if not isinstance(value, bool):
            raise AuditError("invalid audit boolean metadata")
        return
    if key == "version":
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= MAX_DATABASE_INTEGER
        ):
            raise AuditError("invalid audit version metadata")
        return
    if key == "count":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
            raise AuditError("invalid audit count metadata")
        return
    if key == "changed_fields":
        if not isinstance(value, list) or not 1 <= len(value) <= 50:
            raise AuditError("invalid audit changed_fields metadata")
        for item in value:
            if not isinstance(item, str) or item not in CHANGED_FIELD_NAMES:
                raise AuditError("invalid audit field name")
        return
    raise AuditError("unsupported audit metadata field")
