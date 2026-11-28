from abc import ABC, abstractmethod
from uuid import UUID

from src.domain.entities.occupancy import Occupancy
from src.domain.value_objects.time_range import TimeRange


class IOccupancyRepository(ABC):
    @abstractmethod
    async def add(self, occupancy: Occupancy) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_active(self, *, lot_id: UUID, period: TimeRange) -> list[Occupancy]:
        raise NotImplementedError

    @abstractmethod
    async def release(self, occupancy_id: UUID) -> bool:
        raise NotImplementedError
