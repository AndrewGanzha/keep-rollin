from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from src.domain.entities.outbox_message import OutboxMessage


class IOutboxRepository(ABC):
    @abstractmethod
    async def add(self, message: OutboxMessage) -> None:
        raise NotImplementedError

    @abstractmethod
    async def claim_due(self, *, now: datetime, limit: int) -> list[OutboxMessage]:
        raise NotImplementedError

    @abstractmethod
    async def mark_processed(self, message_id: UUID, *, processed_at: datetime) -> None:
        raise NotImplementedError

    @abstractmethod
    async def mark_failed(
        self,
        message_id: UUID,
        *,
        attempts: int,
        available_at: datetime,
        status: str,
        error: str,
    ) -> None:
        raise NotImplementedError
