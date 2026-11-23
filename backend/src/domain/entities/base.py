from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.domain.exceptions import CatalogDomainError


@dataclass(frozen=True)
class Entity:
    id: UUID
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise CatalogDomainError("id must be a UUID")
        if not isinstance(self.created_at, datetime) or not isinstance(self.updated_at, datetime):
            raise CatalogDomainError("created_at and updated_at must be datetimes")
