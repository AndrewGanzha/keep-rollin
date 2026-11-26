from dataclasses import dataclass

from src.application.dtos.admin_settings_dto import (
    AdminSettingsDTO,
    SettingsPoliciesPatch,
    merge_policies,
)
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_admin_settings_repository import IAdminSettingsRepository
from src.domain.entities.tenant_profile import SettingsNotFoundError


@dataclass(frozen=True)
class GetAdminSettingsQuery:
    pass


class GetAdminSettingsHandler(IHandler[GetAdminSettingsQuery, AdminSettingsDTO]):
    def __init__(self, repository: IAdminSettingsRepository) -> None:
        self._repository = repository

    async def handle(self, request: GetAdminSettingsQuery) -> AdminSettingsDTO:
        state = await self._repository.get()
        if state is None:
            raise SettingsNotFoundError("settings not found")
        return AdminSettingsDTO.from_state(state)


@dataclass(frozen=True)
class UpdateSettingsCommand:
    version: int
    changes: dict[str, object]
    policies_patch: SettingsPoliciesPatch | None


class UpdateSettingsHandler(IHandler[UpdateSettingsCommand, AdminSettingsDTO]):
    def __init__(self, repository: IAdminSettingsRepository) -> None:
        self._repository = repository

    async def handle(self, request: UpdateSettingsCommand) -> AdminSettingsDTO:
        current = await self._repository.get()
        if current is None:
            raise SettingsNotFoundError("settings not found")
        policies = merge_policies(current.policies, request.policies_patch)
        state = await self._repository.update(
            version=request.version,
            changes=request.changes,
            policies=policies,
        )
        return AdminSettingsDTO.from_state(state)
