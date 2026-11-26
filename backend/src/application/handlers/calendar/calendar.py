from dataclasses import dataclass
from uuid import UUID

from src.application.dtos.admin_calendar_dto import CalendarEventDTO, LotBlockDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_admin_calendar_repository import (
    IAdminCalendarRepository,
)
from src.domain.value_objects.time_range import TimeRange


@dataclass(frozen=True)
class CalendarQuery:
    period: TimeRange
    category_id: UUID | None = None
    lot_id: UUID | None = None
    status: str | None = None


class ListCalendarHandler(IHandler[CalendarQuery, list[CalendarEventDTO]]):
    def __init__(self, repository: IAdminCalendarRepository) -> None:
        self._repository = repository

    async def handle(self, request: CalendarQuery) -> list[CalendarEventDTO]:
        events = await self._repository.list_events(
            period=request.period,
            category_id=request.category_id,
            lot_id=request.lot_id,
            status=request.status,
        )
        return [CalendarEventDTO.from_domain(event) for event in events]


@dataclass(frozen=True)
class LotCalendarQuery:
    lot_id: UUID
    period: TimeRange


class GetLotCalendarHandler(IHandler[LotCalendarQuery, list[CalendarEventDTO] | None]):
    def __init__(self, repository: IAdminCalendarRepository) -> None:
        self._repository = repository

    async def handle(self, request: LotCalendarQuery) -> list[CalendarEventDTO] | None:
        events = await self._repository.lot_events(
            lot_id=request.lot_id,
            period=request.period,
        )
        if events is None:
            return None
        return [CalendarEventDTO.from_domain(event) for event in events]


@dataclass(frozen=True)
class CreateBlockCommand:
    lot_id: UUID
    period: TimeRange
    reason: str
    created_by: UUID


class CreateBlockHandler(IHandler[CreateBlockCommand, LotBlockDTO]):
    def __init__(self, repository: IAdminCalendarRepository) -> None:
        self._repository = repository

    async def handle(self, request: CreateBlockCommand) -> LotBlockDTO:
        occupancy = await self._repository.create_block(
            lot_id=request.lot_id,
            period=request.period,
            reason=request.reason,
            created_by=request.created_by,
        )
        return LotBlockDTO.from_domain(occupancy)


@dataclass(frozen=True)
class DeleteBlockCommand:
    lot_id: UUID
    block_id: UUID


class DeleteBlockHandler(IHandler[DeleteBlockCommand, None]):
    def __init__(self, repository: IAdminCalendarRepository) -> None:
        self._repository = repository

    async def handle(self, request: DeleteBlockCommand) -> None:
        await self._repository.release_block(
            lot_id=request.lot_id,
            block_id=request.block_id,
        )
