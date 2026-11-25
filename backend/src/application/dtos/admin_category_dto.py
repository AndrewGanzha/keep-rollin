from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from src.application.dtos.characteristic_dto import CharacteristicDTO
from src.domain.entities.category import Category


class AdminCategoryDTO(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    is_archived: bool
    version: int
    characteristics: list[CharacteristicDTO]

    @classmethod
    def from_domain(cls, category: Category) -> Self:
        return cls(
            id=category.id,
            name=category.name.value,
            slug=category.slug.value,
            description=category.description,
            is_archived=category.is_archived,
            version=category.version,
            characteristics=[
                CharacteristicDTO.from_domain(item) for item in category.sorted_characteristics()
            ],
        )


class AdminCategoryPageDTO(BaseModel):
    items: list[AdminCategoryDTO]
    total: int
    limit: int
    offset: int


class CreateCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    description: str | None = None

    @field_validator("name", "slug", "description")
    @classmethod
    def reject_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        return value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class UpdateCategoryRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9-]+$",
    )
    description: str | None = None
    is_archived: bool | None = None
    version: int = Field(ge=1)

    @field_validator("name", "slug", "description")
    @classmethod
    def reject_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        return value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        mutable = {"name", "slug", "description", "is_archived"}
        if not self.model_fields_set & mutable:
            raise ValueError("at least one mutable field must be provided")
        for field in ("name", "slug", "is_archived"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self
