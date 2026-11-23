from typing import Self

from pydantic import Field, StrictInt, ValidationError, model_validator

from src.domain.exceptions import InvalidAllowedDurationsError
from src.domain.value_objects.base import FrozenRootModel


class AllowedDurations(FrozenRootModel[tuple[StrictInt, ...]]):
    root: tuple[StrictInt, ...] = Field(min_length=1, max_length=365)

    @model_validator(mode="after")
    def validate_durations(self) -> Self:
        if any(item < 1 or item > 365 for item in self.root):
            raise ValueError("Durations must be integers from 1 to 365")
        if list(self.root) != sorted(set(self.root)):
            raise ValueError("Durations must be unique and sorted ascending")
        return self

    @classmethod
    def create(cls, value: object) -> Self:
        payload = tuple(value) if isinstance(value, list) else value
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise InvalidAllowedDurationsError("Allowed durations are invalid") from exc

    @property
    def value(self) -> list[int]:
        return list(self.root)

    @property
    def minimum(self) -> int:
        return self.root[0]
