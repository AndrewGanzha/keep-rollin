import re
from typing import Self

from pydantic import Field, ValidationError, model_validator

from src.domain.exceptions import InvalidSlugError
from src.domain.value_objects.base import FrozenRootModel

SLUG_RE = re.compile(r"^[a-z0-9-]+$")


class Slug(FrozenRootModel[str]):
    root: str = Field(strict=True, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_format(self) -> Self:
        if not SLUG_RE.fullmatch(self.root):
            raise ValueError("Slug may contain only lowercase letters, digits and hyphens")
        return self

    @classmethod
    def create(cls, value: object) -> Self:
        try:
            return cls.model_validate(value)
        except ValidationError as exc:
            raise InvalidSlugError("Slug is invalid") from exc

    @property
    def value(self) -> str:
        return self.root
