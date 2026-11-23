from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from src.domain.entities.lot import Lot
from src.domain.value_objects.slug import Slug


@dataclass(frozen=True)
class LotListFilters:
    category_id: UUID | None = None
    query: str | None = None


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
