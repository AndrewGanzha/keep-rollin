from typing import Self
from uuid import UUID

from pydantic import BaseModel

from src.application.dtos.characteristic_dto import CharacteristicDTO
from src.domain.entities.category import Category


class CategoryDTO(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    is_archived: bool
    characteristics: list[CharacteristicDTO]

    @classmethod
    def from_domain(cls, category: Category) -> Self:
        return cls(
            id=category.id,
            name=category.name.value,
            slug=category.slug.value,
            description=category.description,
            is_archived=category.is_archived,
            characteristics=[
                CharacteristicDTO.from_domain(item) for item in category.sorted_characteristics()
            ],
        )
