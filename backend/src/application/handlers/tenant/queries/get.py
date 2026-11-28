from dataclasses import dataclass

from src.application.dtos.tenant_dto import TenantDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_tenant_profile_repository import ITenantProfileRepository


@dataclass(frozen=True)
class GetPublicTenantQuery:
    pass


class GetPublicTenantHandler(IHandler[GetPublicTenantQuery, TenantDTO | None]):
    def __init__(self, repository: ITenantProfileRepository) -> None:
        self._repository = repository

    async def handle(self, request: GetPublicTenantQuery) -> TenantDTO | None:
        tenant = await self._repository.get_current()
        return None if tenant is None else TenantDTO.from_domain(tenant)
