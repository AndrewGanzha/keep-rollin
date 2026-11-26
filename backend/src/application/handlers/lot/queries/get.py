from dataclasses import dataclass

from src.application.dtos.lot_dto import LotDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_lot_repository import ILotRepository
from src.domain.exceptions import InvalidSlugError
from src.domain.value_objects.slug import Slug


@dataclass(frozen=True)
class GetLotQuery:
    slug: str


class GetLotHandler(IHandler[GetLotQuery, LotDTO | None]):
    def __init__(self, repository: ILotRepository) -> None:
        self._repository = repository

    async def handle(self, request: GetLotQuery) -> LotDTO | None:
        try:
            slug = Slug.create(request.slug)
        except InvalidSlugError:
            return None

        lot = await self._repository.get_active_by_slug(slug)
        if lot is None or not lot.is_bookable:
            return None
        return LotDTO.from_domain(lot)
