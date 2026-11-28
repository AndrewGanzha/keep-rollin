from dataclasses import dataclass

from src.application.dtos.admin_category_dto import AdminCategoryDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_admin_category_repository import IAdminCategoryRepository


@dataclass(frozen=True)
class CreateCategoryCommand:
    name: str
    slug: str
    description: str | None


class CreateCategoryHandler(IHandler[CreateCategoryCommand, AdminCategoryDTO]):
    def __init__(self, repository: IAdminCategoryRepository) -> None:
        self._repository = repository

    async def handle(self, request: CreateCategoryCommand) -> AdminCategoryDTO:
        category = await self._repository.create(
            name=request.name,
            slug=request.slug,
            description=request.description,
        )
        return AdminCategoryDTO.from_domain(category)
