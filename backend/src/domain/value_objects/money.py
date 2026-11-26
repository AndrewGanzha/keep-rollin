from typing import Self

from pydantic import Field, ValidationError

from src.domain.exceptions import InvalidMoneyError
from src.domain.value_objects.base import FrozenRootModel


class MoneyAmount(FrozenRootModel[int]):
    root: int = Field(strict=True, ge=1)

    @classmethod
    def create(cls, value: object) -> Self:
        try:
            return cls.model_validate(value)
        except ValidationError as exc:
            raise InvalidMoneyError("Money amount must be a positive integer") from exc

    @property
    def value(self) -> int:
        return self.root
