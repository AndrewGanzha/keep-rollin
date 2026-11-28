from collections.abc import Mapping

_EVENTS = {
    "verification.approved": False,
    "verification.rejected": True,
    "booking.confirmed": False,
    "rental.closed": False,
    "booking.cancelled": False,
    "rental.ending_soon": False,
    "rental.overdue.user": True,
    "rental.overdue.admin": True,
    "ticket.created.admin": True,
    "ticket.updated.user": False,
    "ticket.resolved.user": True,
}
_STAFF_EVENTS = frozenset({"rental.overdue.admin", "ticket.created.admin"})


def applicable_events(role: str) -> tuple[str, ...]:
    if role in ("admin", "owner"):
        return tuple(_EVENTS)
    return tuple(event for event in _EVENTS if event not in _STAFF_EVENTS)


def locked_events(role: str) -> tuple[str, ...]:
    return tuple(event for event in applicable_events(role) if _EVENTS[event])


def push_enabled(values: Mapping[str, object]) -> bool:
    enabled = values.get("push_enabled")
    return enabled if isinstance(enabled, bool) else True


def email_allowed(values: Mapping[str, object], event_type: str, role: str) -> bool:
    if event_type not in applicable_events(role):
        return False
    if _EVENTS[event_type]:
        return True
    settings = values.get("email_by_event")
    enabled = settings.get(event_type) if isinstance(settings, Mapping) else None
    return enabled if isinstance(enabled, bool) else True
