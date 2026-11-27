from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from src.domain.entities.lot import Lot
from src.domain.value_objects.slug import Slug
from src.domain.value_objects.time_range import TimeRange

LotSort = Literal["newest", "name_asc", "price_asc", "price_desc"]


class InvalidLotCharacteristicFilter(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LotListFilters:
    category_id: UUID | None = None
    query: str | None = None
    characteristics: tuple[tuple[str, str], ...] = ()
    available_period: TimeRange | None = None
    sort: LotSort = "newest"


class ILotRepository(ABC):
    @abstractmethod
    async def list_active(
        self,
        *,
        filters: LotListFilters,
        limit: int,
        offset: int,
    ) -> tuple[list[Lot], int]:
        raise NotImplementedError

    @abstractmethod
    async def get_active_by_slug(self, slug: Slug) -> Lot | None:
        raise NotImplementedError
