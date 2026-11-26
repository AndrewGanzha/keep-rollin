from abc import ABC, abstractmethod
from uuid import UUID

from src.domain.entities.occupancy import Occupancy
from src.domain.value_objects.time_range import TimeRange


class IAdminCalendarRepository(ABC):
    @abstractmethod
    async def list_events(
        self,
        *,
        period: TimeRange,
        category_id: UUID | None,
        lot_id: UUID | None,
        status: str | None,
    ) -> list[Occupancy]:
        raise NotImplementedError

    @abstractmethod
    async def lot_events(
        self,
        *,
        lot_id: UUID,
        period: TimeRange,
    ) -> list[Occupancy] | None:
        raise NotImplementedError

    @abstractmethod
    async def create_block(
        self,
        *,
        lot_id: UUID,
        period: TimeRange,
        reason: str,
        created_by: UUID,
    ) -> Occupancy:
        raise NotImplementedError

    @abstractmethod
    async def release_block(self, *, lot_id: UUID, block_id: UUID) -> bool:
        raise NotImplementedError
