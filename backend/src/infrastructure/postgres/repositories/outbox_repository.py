from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import literal_column, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from src.application.repositories.i_outbox_repository import IOutboxRepository
from src.domain.entities.outbox_message import (
    DuplicateOutboxEventError,
    OutboxMessage,
    OutboxStatus,
)
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord

UNIQUE_VIOLATION = "23505"


class OutboxRepository(IOutboxRepository):
    def __init__(
        self, session: AsyncSession, *, email_event_types: frozenset[str] | None = None
    ) -> None:
        self._session = session
        self._email_event_types = email_event_types

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))

    async def add(self, message: OutboxMessage) -> None:
        record = OutboxMessageRecord(
            id=message.id,
            tenant_id=self._tenant_id(),
            event_type=message.event_type,
            entity_id=message.entity_id,
            user_id=message.user_id,
            channel=message.channel,
            payload=dict(message.payload),
            status=message.status,
            attempts=message.attempts,
            available_at=message.available_at,
            last_error=message.last_error,
            processed_at=message.processed_at,
            created_at=message.created_at,
            updated_at=message.updated_at,
        )
        self._session.add(record)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION:
                raise DuplicateOutboxEventError("Outbox event already exists") from exc
            raise

    async def claim_due(self, *, now: datetime, limit: int) -> list[OutboxMessage]:
        statement = (
            select(OutboxMessageRecord)
            .where(
                OutboxMessageRecord.tenant_id == self._tenant_id(),
                OutboxMessageRecord.status == literal_column("'pending'"),
                OutboxMessageRecord.available_at <= now,
            )
            .order_by(
                OutboxMessageRecord.available_at.asc(),
                OutboxMessageRecord.created_at.asc(),
                OutboxMessageRecord.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if self._email_event_types is not None:
            statement = statement.options(defer(OutboxMessageRecord.payload, raiseload=True)).where(
                OutboxMessageRecord.event_type.in_(self._email_event_types),
                or_(
                    OutboxMessageRecord.channel.is_(None),
                    OutboxMessageRecord.channel == "email",
                ),
            )
        result = await self._session.execute(statement)
        return [self._to_domain(record) for record in result.scalars().all()]

    async def mark_processed(self, message_id: UUID, *, processed_at: datetime) -> None:
        await self._session.execute(
            update(OutboxMessageRecord)
            .where(OutboxMessageRecord.id == message_id)
            .values(
                status="processed",
                processed_at=processed_at,
                updated_at=processed_at,
                last_error=None,
            )
        )

    async def mark_failed(
        self,
        message_id: UUID,
        *,
        attempts: int,
        available_at: datetime,
        status: str,
        error: str,
    ) -> None:
        await self._session.execute(
            update(OutboxMessageRecord)
            .where(OutboxMessageRecord.id == message_id)
            .values(
                attempts=attempts,
                available_at=available_at,
                status=status,
                last_error=error,
                updated_at=available_at,
            )
        )

    def _to_domain(self, record: OutboxMessageRecord) -> OutboxMessage:
        return OutboxMessage(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            event_type=record.event_type,
            entity_id=record.entity_id,
            user_id=record.user_id,
            channel=record.channel,
            payload=record.payload if self._email_event_types is None else {},
            status=cast(OutboxStatus, record.status),
            attempts=record.attempts,
            available_at=record.available_at,
            last_error=record.last_error,
            processed_at=record.processed_at,
        )
