from abc import ABC, abstractmethod

from src.domain.entities.tenant_profile import TenantProfile


class ITenantProfileRepository(ABC):
    @abstractmethod
    async def get_current(self) -> TenantProfile | None:
        raise NotImplementedError
