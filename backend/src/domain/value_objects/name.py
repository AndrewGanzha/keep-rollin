from typing import Self

from pydantic import Field, ValidationError

from src.domain.exceptions import InvalidNameError
from src.domain.value_objects.base import FrozenRootModel


class EntityName(FrozenRootModel[str]):
    root: str = Field(strict=True, min_length=1, max_length=120)

    @classmethod
    def create(cls, value: object) -> Self:
        try:
            return cls.model_validate(value)
        except ValidationError as exc:
            raise InvalidNameError("Name must be between 1 and 120 characters") from exc

    @property
    def value(self) -> str:
        return self.root
