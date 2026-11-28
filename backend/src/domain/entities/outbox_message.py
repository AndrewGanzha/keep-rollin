from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from src.domain.entities.base import Entity
from src.domain.exceptions import CatalogDomainError

OutboxStatus = Literal["pending", "processing", "processed", "failed"]


class OutboxError(CatalogDomainError):
    pass


class DuplicateOutboxEventError(OutboxError):
    pass


@dataclass(frozen=True)
class OutboxMessage(Entity):
    event_type: str
    entity_id: UUID | None
    user_id: UUID | None
    channel: str | None
    payload: Mapping[str, object]
    status: OutboxStatus
    attempts: int
    available_at: datetime
    last_error: str | None
    processed_at: datetime | None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.event_type, str) or not self.event_type:
            raise OutboxError("event_type must be a non-empty string")
        if self.entity_id is not None and not isinstance(self.entity_id, UUID):
            raise OutboxError("entity_id must be a UUID or None")
        if self.user_id is not None and not isinstance(self.user_id, UUID):
            raise OutboxError("user_id must be a UUID or None")
        if self.channel is not None and not isinstance(self.channel, str):
            raise OutboxError("channel must be a string or None")
        if not isinstance(self.payload, Mapping):
            raise OutboxError("payload must be a mapping")
        if self.status not in ("pending", "processing", "processed", "failed"):
            raise OutboxError("status is invalid")
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int):
            raise OutboxError("attempts must be an integer")
        if self.attempts < 0:
            raise OutboxError("attempts must not be negative")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise OutboxError("available_at must be timezone-aware")
        if self.last_error is not None and not isinstance(self.last_error, str):
            raise OutboxError("last_error must be a string or None")
        if self.processed_at is not None and (
            self.processed_at.tzinfo is None or self.processed_at.utcoffset() is None
        ):
            raise OutboxError("processed_at must be timezone-aware or None")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
