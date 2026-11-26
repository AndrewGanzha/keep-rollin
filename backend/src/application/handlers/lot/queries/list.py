from dataclasses import dataclass
from uuid import UUID

from src.application.dtos.lot_dto import LotDTO, LotPageDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_lot_repository import ILotRepository, LotListFilters


@dataclass(frozen=True)
class ListLotsQuery:
    category_id: UUID | None
    query: str | None
    limit: int
    offset: int


class ListLotsHandler(IHandler[ListLotsQuery, LotPageDTO]):
    def __init__(self, repository: ILotRepository) -> None:
        self._repository = repository

    async def handle(self, request: ListLotsQuery) -> LotPageDTO:
        lots, total = await self._repository.list_active(
            filters=LotListFilters(
                category_id=request.category_id,
                query=request.query or None,
            ),
            limit=request.limit,
            offset=request.offset,
        )
        return LotPageDTO(
            items=[LotDTO.from_domain(lot) for lot in lots],
            total=total,
            limit=request.limit,
            offset=request.offset,
        )
