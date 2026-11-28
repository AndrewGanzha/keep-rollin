from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.audit import AuditEntry
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))

    async def add(self, entry: AuditEntry) -> None:
        self._session.add(
            AuditLogRecord(
                id=entry.id,
                tenant_id=self._tenant_id(),
                action=entry.action,
                actor_id=entry.actor_id,
                actor_role=entry.actor_role,
                ip=entry.ip,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                metadata_json=entry.metadata,
                request_id=entry.request_id,
                created_at=entry.created_at,
            )
        )
        await self._session.flush()

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
    ) -> list[AuditEntry]:
        if (entity_type is None) != (entity_id is None):
            raise ValueError("entity_type and entity_id must be provided together")
        query = select(AuditLogRecord)
        if actor_id is not None:
            query = query.where(AuditLogRecord.actor_id == actor_id)
        if action is not None:
            query = query.where(AuditLogRecord.action == action)
        if entity_type is not None:
            query = query.where(AuditLogRecord.entity_type == entity_type)
        if entity_id is not None:
            query = query.where(AuditLogRecord.entity_id == entity_id)
        if from_at is not None:
            query = query.where(AuditLogRecord.created_at >= from_at)
        if to_at is not None:
            query = query.where(AuditLogRecord.created_at < to_at)
        if before is not None:
            before_at, before_id = before
            query = query.where(
                (AuditLogRecord.created_at < before_at)
                | ((AuditLogRecord.created_at == before_at) & (AuditLogRecord.id < before_id))
            )
        query = query.order_by(
            AuditLogRecord.created_at.desc(),
            AuditLogRecord.id.desc(),
        ).limit(limit)
        rows = (await self._session.execute(query)).scalars().all()
        return [self._to_entry(row) for row in rows]

    async def purge_before(self, *, cutoff: datetime, batch_size: int) -> int:
        subquery = (
            select(AuditLogRecord.id)
            .where(AuditLogRecord.created_at < cutoff)
            .order_by(AuditLogRecord.created_at, AuditLogRecord.id)
            .limit(batch_size)
        )
        result = await self._session.execute(
            delete(AuditLogRecord).where(AuditLogRecord.id.in_(subquery))
        )
        return int(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    def _to_entry(record: AuditLogRecord) -> AuditEntry:
        return AuditEntry(
            id=record.id,
            tenant_id=record.tenant_id,
            action=record.action,
            actor_id=record.actor_id,
            actor_role=record.actor_role,
            ip=str(record.ip) if record.ip is not None else None,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            metadata=dict(record.metadata_json or {}),
            request_id=record.request_id,
            created_at=record.created_at,
        )
