from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from src.application.dtos.admin_category_dto import AdminCategoryDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_admin_category_repository import (
    CharacteristicUpsert,
    IAdminCategoryRepository,
)


@dataclass(frozen=True)
class UpdateCategoryCharacteristicsCommand:
    category_id: UUID
    version: int
    definitions: Sequence[CharacteristicUpsert]


class UpdateCategoryCharacteristicsHandler(
    IHandler[UpdateCategoryCharacteristicsCommand, AdminCategoryDTO]
):
    def __init__(self, repository: IAdminCategoryRepository) -> None:
        self._repository = repository

    async def handle(
        self,
        request: UpdateCategoryCharacteristicsCommand,
    ) -> AdminCategoryDTO:
        category = await self._repository.update_characteristics(
            request.category_id,
            version=request.version,
            definitions=request.definitions,
        )
        return AdminCategoryDTO.from_domain(category)
