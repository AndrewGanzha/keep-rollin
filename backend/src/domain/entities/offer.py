from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from src.domain.entities.base import Entity
from src.domain.exceptions import CatalogDomainError

OfferStatus = Literal["draft", "active", "archived"]


class OfferNotFoundError(CatalogDomainError):
    pass


class OfferNotEditableError(CatalogDomainError):
    pass


class OfferNotActiveError(CatalogDomainError):
    pass


@dataclass(frozen=True)
class OfferVersion(Entity):
    version: int
    title: str
    body: str
    status: OfferStatus
    published_at: datetime | None

    def __post_init__(self) -> None:
        super().__post_init__()
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise CatalogDomainError("offer version must be a positive integer")
        if not isinstance(self.title, str) or not 1 <= len(self.title.strip()) <= 200:
            raise CatalogDomainError("offer title must be between 1 and 200 characters")
        if not isinstance(self.body, str) or not 1 <= len(self.body.strip()) <= 20000:
            raise CatalogDomainError("offer body must be between 1 and 20000 characters")
        if self.status not in ("draft", "active", "archived"):
            raise CatalogDomainError("offer status is invalid")
        if self.published_at is not None and not isinstance(self.published_at, datetime):
            raise CatalogDomainError("offer published_at must be a datetime or None")


@dataclass(frozen=True)
class OfferAcceptance:
    id: UUID
    user_id: UUID
    offer_version_id: UUID
    accepted_at: datetime
    ip: str | None
