from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from src.domain.entities.category import Category
from src.domain.entities.characteristic import CharacteristicType


@dataclass(frozen=True)
class CharacteristicUpsert:
    code: str
    name: str
    type: CharacteristicType
    unit: str | None
    is_required: bool
    options: tuple[str, ...]
    sort: int
    is_archived: bool


class IAdminCategoryRepository(ABC):
    @abstractmethod
    async def list(
        self,
        *,
        include_archived: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Category], int]:
        raise NotImplementedError

    @abstractmethod
    async def create(
        self,
        *,
        name: str,
        slug: str,
        description: str | None,
    ) -> Category:
        raise NotImplementedError

    @abstractmethod
    async def update(
        self,
        category_id: UUID,
        *,
        version: int,
        changes: Mapping[str, object],
    ) -> Category:
        raise NotImplementedError

    @abstractmethod
    async def update_characteristics(
        self,
        category_id: UUID,
        *,
        version: int,
        definitions: Sequence[CharacteristicUpsert],
    ) -> Category:
        raise NotImplementedError
