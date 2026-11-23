from dataclasses import dataclass
from typing import Literal

from src.domain.entities.base import Entity
from src.domain.exceptions import CatalogDomainError
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.slug import Slug

CharacteristicType = Literal["number", "text", "select"]


@dataclass(frozen=True)
class Characteristic(Entity):
    code: Slug
    name: EntityName
    type: CharacteristicType
    unit: str | None
    is_required: bool
    options: tuple[str, ...]
    sort: int
    is_archived: bool

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.code, Slug) or not isinstance(self.name, EntityName):
            raise CatalogDomainError("code and name must be value objects")
        if not isinstance(self.type, str) or self.type not in ("number", "text", "select"):
            raise CatalogDomainError("type must be number, text or select")
        if self.unit is not None and not isinstance(self.unit, str):
            raise CatalogDomainError("unit must be a string or None")
        if not isinstance(self.is_required, bool) or not isinstance(self.is_archived, bool):
            raise CatalogDomainError("is_required and is_archived must be booleans")
        if isinstance(self.sort, bool) or not isinstance(self.sort, int):
            raise CatalogDomainError("sort must be an integer")
        if not isinstance(self.options, (list, tuple)):
            raise CatalogDomainError("Characteristic options must be a sequence of strings")
        options = tuple(self.options)
        if any(not isinstance(option, str) for option in options):
            raise CatalogDomainError("Characteristic options must be strings")
        object.__setattr__(self, "options", options)
