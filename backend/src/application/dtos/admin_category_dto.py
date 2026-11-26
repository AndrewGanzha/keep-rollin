from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.entities.category import Category
from src.domain.entities.characteristic import Characteristic

CharacteristicType = Literal["number", "text", "select"]


class AdminCharacteristicDTO(BaseModel):
    id: UUID
    code: str
    name: str
    type: CharacteristicType
    unit: str | None
    is_required: bool
    options: list[str]
    sort: int
    is_archived: bool

    @classmethod
    def from_domain(cls, characteristic: Characteristic) -> Self:
        return cls(
            id=characteristic.id,
            code=characteristic.code.value,
            name=characteristic.name.value,
            type=characteristic.type,
            unit=characteristic.unit,
            is_required=characteristic.is_required,
            options=list(characteristic.options),
            sort=characteristic.sort,
            is_archived=characteristic.is_archived,
        )


class AdminCategoryDTO(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    is_archived: bool
    version: int
    characteristics: list[AdminCharacteristicDTO]

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
                AdminCharacteristicDTO.from_domain(item)
                for item in category.sorted_characteristics()
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


class CharacteristicDefinitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=120)
    type: CharacteristicType
    unit: str | None = Field(default=None, max_length=32)
    is_required: bool = False
    options: list[str] = Field(default_factory=list)
    sort: int = Field(default=0, ge=0, le=10000)
    is_archived: bool = False

    @field_validator("code", "name", "unit")
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

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        if any("\x00" in option or not option.strip() for option in value):
            raise ValueError("options must be non-empty strings without NUL")
        if len(set(value)) != len(value):
            raise ValueError("options must be unique")
        return value

    @model_validator(mode="after")
    def validate_type_options(self) -> Self:
        if self.type == "select":
            if not self.options:
                raise ValueError("select characteristics require options")
        elif self.options:
            raise ValueError("only select characteristics may define options")
        return self


class UpdateCharacteristicsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    items: list[CharacteristicDefinitionInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_codes(self) -> Self:
        codes = [item.code for item in self.items]
        if len(set(codes)) != len(codes):
            raise ValueError("characteristic codes must be unique")
        return self
