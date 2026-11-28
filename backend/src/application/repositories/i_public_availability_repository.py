from abc import ABC, abstractmethod
from uuid import UUID

from src.domain.value_objects.time_range import TimeRange


class IPublicAvailabilityRepository(ABC):
    @abstractmethod
    async def get_occupancy_periods(
        self, *, period: TimeRange, category_id: UUID | None
    ) -> tuple[int, list[tuple[UUID, TimeRange]]]:
        """Return the eligible lot count and overlapping active periods clipped to the request."""
        raise NotImplementedError
