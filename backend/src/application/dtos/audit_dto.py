from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field

from src.application.services.audit import AuditEntry


class AuditLogEntryDTO(BaseModel):
    id: UUID
    action: str
    actor_id: UUID | None
    actor_role: str
    entity_type: str
    entity_id: UUID | None
    metadata: dict[str, object]
    ip: str | None
    request_id: str | None
    created_at: datetime

    @classmethod
    def from_entry(cls, entry: AuditEntry) -> Self:
        return cls(
            id=entry.id,
            action=entry.action,
            actor_id=entry.actor_id,
            actor_role=entry.actor_role,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            metadata=entry.metadata,
            ip=entry.ip,
            request_id=entry.request_id,
            created_at=entry.created_at,
        )


class AuditLogPageDTO(BaseModel):
    items: list[AuditLogEntryDTO]
    next_cursor: str | None = Field(default=None)
