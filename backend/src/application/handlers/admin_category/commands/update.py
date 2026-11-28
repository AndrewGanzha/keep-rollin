from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from src.application.dtos.admin_category_dto import AdminCategoryDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_admin_category_repository import IAdminCategoryRepository


@dataclass(frozen=True)
class UpdateCategoryCommand:
    category_id: UUID
    version: int
    changes: Mapping[str, object]


class UpdateCategoryHandler(IHandler[UpdateCategoryCommand, AdminCategoryDTO]):
    def __init__(self, repository: IAdminCategoryRepository) -> None:
        self._repository = repository

    async def handle(self, request: UpdateCategoryCommand) -> AdminCategoryDTO:
        category = await self._repository.update(
            request.category_id,
            version=request.version,
            changes=request.changes,
        )
        return AdminCategoryDTO.from_domain(category)
