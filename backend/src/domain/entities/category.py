from dataclasses import dataclass, field

from src.domain.entities.base import Entity
from src.domain.entities.characteristic import Characteristic
from src.domain.exceptions import CatalogDomainError
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.slug import Slug


class CategoryNotFoundError(CatalogDomainError):
    pass


class CategorySlugTakenError(CatalogDomainError):
    pass


class CategoryVersionConflictError(CatalogDomainError):
    pass


@dataclass(frozen=True)
class Category(Entity):
    name: EntityName
    slug: Slug
    description: str | None
    is_archived: bool
    characteristics: tuple[Characteristic, ...] = field(default_factory=tuple)
    version: int = 1

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.name, EntityName) or not isinstance(self.slug, Slug):
            raise CatalogDomainError("name and slug must be value objects")
        if not isinstance(self.is_archived, bool):
            raise CatalogDomainError("is_archived must be a boolean")
        if self.description is not None and not isinstance(self.description, str):
            raise CatalogDomainError("description must be a string or None")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise CatalogDomainError("version must be a positive integer")
        if not isinstance(self.characteristics, (list, tuple)):
            raise CatalogDomainError("characteristics must be a sequence")
        characteristics = tuple(self.characteristics)
        if any(not isinstance(item, Characteristic) for item in characteristics):
            raise CatalogDomainError("characteristics must contain Characteristic entities")
        object.__setattr__(self, "characteristics", characteristics)

    def sorted_characteristics(self) -> list[Characteristic]:
        return sorted(self.characteristics, key=lambda item: (item.sort, item.code.value))
