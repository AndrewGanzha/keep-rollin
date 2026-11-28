from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from src.application.repositories.i_outbox_repository import IOutboxRepository
from src.domain.entities.outbox_message import OutboxMessage

RETRY_DELAYS_MINUTES = (1, 5, 15)


class OutboxHandler(Protocol):
    async def handle(self, message: OutboxMessage) -> None: ...


class NoopOutboxHandler:
    async def handle(self, message: OutboxMessage) -> None:
        return None


class OutboxWriter:
    def __init__(self, repository: IOutboxRepository) -> None:
        self._repository = repository

    async def enqueue(
        self,
        *,
        event_type: str,
        entity_id: UUID | None = None,
        user_id: UUID | None = None,
        channel: str | None = None,
        payload: Mapping[str, object] | None = None,
        now: datetime | None = None,
    ) -> OutboxMessage:
        timestamp = now or datetime.now(UTC)
        message = OutboxMessage(
            id=uuid4(),
            created_at=timestamp,
            updated_at=timestamp,
            event_type=event_type,
            entity_id=entity_id,
            user_id=user_id,
            channel=channel,
            payload=payload or {},
            status="pending",
            attempts=0,
            available_at=timestamp,
            last_error=None,
            processed_at=None,
        )
        await self._repository.add(message)
        return message


@dataclass(frozen=True)
class OutboxProcessResult:
    claimed: int
    processed: int
    retried: int
    failed: int


class OutboxConsumer:
    def __init__(self, repository: IOutboxRepository) -> None:
        self._repository = repository

    async def process_once(
        self,
        handler: OutboxHandler,
        *,
        now: datetime | None = None,
        limit: int = 20,
        retry_errors: type[Exception] = Exception,
    ) -> OutboxProcessResult:
        timestamp = now or datetime.now(UTC)
        messages = await self._repository.claim_due(now=timestamp, limit=limit)
        processed = 0
        retried = 0
        failed = 0

        for message in messages:
            try:
                await handler.handle(message)
            except retry_errors as exc:
                attempts = message.attempts + 1
                error = str(exc)[:500]
                if attempts <= len(RETRY_DELAYS_MINUTES):
                    await self._repository.mark_failed(
                        message.id,
                        attempts=attempts,
                        available_at=timestamp
                        + timedelta(minutes=RETRY_DELAYS_MINUTES[attempts - 1]),
                        status="pending",
                        error=error,
                    )
                    retried += 1
                else:
                    await self._repository.mark_failed(
                        message.id,
                        attempts=attempts,
                        available_at=timestamp,
                        status="failed",
                        error=error,
                    )
                    failed += 1
            else:
                await self._repository.mark_processed(message.id, processed_at=timestamp)
                processed += 1

        return OutboxProcessResult(
            claimed=len(messages),
            processed=processed,
            retried=retried,
            failed=failed,
        )
