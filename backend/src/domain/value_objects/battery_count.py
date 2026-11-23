from typing import Self

from pydantic import Field, ValidationError

from src.domain.exceptions import InvalidBatteryCountError
from src.domain.value_objects.base import FrozenRootModel
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER


class BatteryCount(FrozenRootModel[int]):
    root: int = Field(strict=True, ge=0, le=MAX_DATABASE_INTEGER)

    @classmethod
    def create(cls, value: object) -> Self:
        try:
            return cls.model_validate(value)
        except ValidationError as exc:
            raise InvalidBatteryCountError(
                "Battery count must be a non-negative 64-bit integer"
            ) from exc

    @property
    def value(self) -> int:
        return self.root
