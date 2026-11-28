from dataclasses import dataclass

from src.application.dtos.admin_category_dto import AdminCategoryDTO, AdminCategoryPageDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_admin_category_repository import IAdminCategoryRepository


@dataclass(frozen=True)
class ListAdminCategoriesQuery:
    include_archived: bool = False
    limit: int = 20
    offset: int = 0


class ListAdminCategoriesHandler(IHandler[ListAdminCategoriesQuery, AdminCategoryPageDTO]):
    def __init__(self, repository: IAdminCategoryRepository) -> None:
        self._repository = repository

    async def handle(self, request: ListAdminCategoriesQuery) -> AdminCategoryPageDTO:
        categories, total = await self._repository.list(
            include_archived=request.include_archived,
            limit=request.limit,
            offset=request.offset,
        )
        return AdminCategoryPageDTO(
            items=[AdminCategoryDTO.from_domain(category) for category in categories],
            total=total,
            limit=request.limit,
            offset=request.offset,
        )
