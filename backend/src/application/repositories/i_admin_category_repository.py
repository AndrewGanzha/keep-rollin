from abc import ABC, abstractmethod
from collections.abc import Mapping
from uuid import UUID

from src.domain.entities.category import Category


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
