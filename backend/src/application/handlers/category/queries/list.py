from dataclasses import dataclass

from src.application.dtos.category_dto import CategoryDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_category_repository import ICategoryRepository


@dataclass(frozen=True)
class ListCategoriesQuery:
    pass


class ListCategoriesHandler(IHandler[ListCategoriesQuery, list[CategoryDTO]]):
    def __init__(self, repository: ICategoryRepository) -> None:
        self._repository = repository

    async def handle(self, request: ListCategoriesQuery) -> list[CategoryDTO]:
        categories = await self._repository.list_active()
        return [CategoryDTO.from_domain(category) for category in categories]
