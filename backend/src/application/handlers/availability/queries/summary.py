from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.application.dtos.availability_dto import AvailabilitySummaryDTO, AvailabilityWindowDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_public_availability_repository import (
    IPublicAvailabilityRepository,
)
from src.domain.value_objects.time_range import TimeRange


@dataclass(frozen=True)
class GetAvailabilitySummaryQuery:
    period: TimeRange
    category_id: UUID | None


class GetAvailabilitySummaryHandler(IHandler[GetAvailabilitySummaryQuery, AvailabilitySummaryDTO]):
    def __init__(self, repository: IPublicAvailabilityRepository) -> None:
        self._repository = repository

    async def handle(self, request: GetAvailabilitySummaryQuery) -> AvailabilitySummaryDTO:
        period = request.period
        lots_total, occupancies = await self._repository.get_occupancy_periods(
            period=period, category_id=request.category_id
        )
        if lots_total == 0:
            return AvailabilitySummaryDTO(lots_total=0, lots_free=0, windows=[])

        occupied_lots: set[UUID] = set()
        deltas: defaultdict[datetime, int] = defaultdict(int, {period.end: 0})
        # PostgreSQL excludes overlapping active intervals for a given lot.
        for lot_id, occupancy in occupancies:
            occupied_lots.add(lot_id)
            deltas[occupancy.start] -= 1
            deltas[occupancy.end] += 1

        windows: list[AvailabilityWindowDTO] = []
        window_start = period.start
        free_count = lots_total + deltas.pop(period.start, 0)
        for boundary, delta in sorted(deltas.items()):
            if delta == 0 and boundary != period.end:
                continue
            windows.append(
                AvailabilityWindowDTO(start=window_start, end=boundary, lots_free=free_count)
            )
            window_start = boundary
            free_count += delta

        return AvailabilitySummaryDTO(
            lots_total=lots_total, lots_free=lots_total - len(occupied_lots), windows=windows
        )
