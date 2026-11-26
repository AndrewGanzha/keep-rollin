from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from src.domain.entities.tenant_profile import TenantPolicies


@dataclass(frozen=True)
class AdminSettingsState:
    logo_url: str | None
    primary_color: str
    timezone: str
    currency: str
    vapid_public_key: str | None
    policies: TenantPolicies
    version: int


class IAdminSettingsRepository(ABC):
    @abstractmethod
    async def get(self) -> AdminSettingsState | None:
        raise NotImplementedError

    @abstractmethod
    async def update(
        self,
        *,
        version: int,
        changes: Mapping[str, object],
        policies: TenantPolicies | None,
    ) -> AdminSettingsState:
        raise NotImplementedError
