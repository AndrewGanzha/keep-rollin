from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from src.domain.entities.offer import OfferAcceptance, OfferVersion


@dataclass(frozen=True)
class OfferAcceptanceState:
    acceptance: OfferAcceptance
    version_number: int


class IOfferRepository(ABC):
    @abstractmethod
    async def list_versions(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[OfferVersion], int]:
        raise NotImplementedError

    @abstractmethod
    async def get(self, offer_id: UUID) -> OfferVersion | None:
        raise NotImplementedError

    @abstractmethod
    async def create_draft(self, *, title: str, body: str) -> OfferVersion:
        raise NotImplementedError

    @abstractmethod
    async def update_draft(
        self,
        offer_id: UUID,
        *,
        changes: Mapping[str, object],
    ) -> OfferVersion:
        raise NotImplementedError

    @abstractmethod
    async def publish(self, offer_id: UUID) -> OfferVersion:
        raise NotImplementedError

    @abstractmethod
    async def get_current(self) -> OfferVersion | None:
        raise NotImplementedError

    @abstractmethod
    async def accept(
        self,
        *,
        user_id: UUID,
        offer_version_id: UUID,
        ip: str | None,
    ) -> OfferAcceptanceState:
        raise NotImplementedError

    @abstractmethod
    async def list_acceptances(self, *, user_id: UUID) -> list[OfferAcceptanceState]:
        raise NotImplementedError

    @abstractmethod
    async def has_accepted_current(self, *, user_id: UUID) -> bool:
        raise NotImplementedError
