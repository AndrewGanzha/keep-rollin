from dataclasses import dataclass

from src.application.dtos.availability_dto import (
    AvailabilityDTO,
    BusyIntervalDTO,
    FreeWindowDTO,
)
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_lot_repository import ILotRepository
from src.application.repositories.i_occupancy_repository import IOccupancyRepository
from src.domain.entities.occupancy import Occupancy
from src.domain.exceptions import InvalidSlugError
from src.domain.value_objects.slug import Slug
from src.domain.value_objects.time_range import TimeRange


@dataclass(frozen=True)
class GetLotAvailabilityQuery:
    slug: str
    period: TimeRange


class GetLotAvailabilityHandler(IHandler[GetLotAvailabilityQuery, AvailabilityDTO | None]):
    def __init__(
        self,
        lot_repository: ILotRepository,
        occupancy_repository: IOccupancyRepository,
    ) -> None:
        self._lot_repository = lot_repository
        self._occupancy_repository = occupancy_repository

    async def handle(self, request: GetLotAvailabilityQuery) -> AvailabilityDTO | None:
        try:
            slug = Slug.create(request.slug)
        except InvalidSlugError:
            return None

        lot = await self._lot_repository.get_active_by_slug(slug)
        if lot is None:
            return None

        occupancies = await self._occupancy_repository.list_active(
            lot_id=lot.id,
            period=request.period,
        )
        busy = [
            BusyIntervalDTO(
                start=occupancy.period.start,
                end=occupancy.period.end,
                kind="busy",
            )
            for occupancy in occupancies
        ]
        return AvailabilityDTO.build(
            lot_id=lot.id,
            from_=request.period.start,
            to=request.period.end,
            busy=busy,
            next_free=self._next_free(request.period, occupancies),
        )

    @staticmethod
    def _next_free(period: TimeRange, occupancies: list[Occupancy]) -> FreeWindowDTO | None:
        cursor = period.start
        for occupancy in sorted(occupancies, key=lambda item: item.period.start):
            if occupancy.period.end <= cursor:
                continue
            if occupancy.period.start > cursor:
                end = min(occupancy.period.start, period.end)
                if cursor < end:
                    return FreeWindowDTO(start=cursor, end=end)
            if occupancy.period.end > cursor:
                cursor = occupancy.period.end
            if cursor >= period.end:
                return None
        if cursor < period.end:
            return FreeWindowDTO(start=cursor, end=period.end)
        return None
