from typing import Literal, Self

from pydantic import ConfigDict, Field, ValidationError

from src.domain.exceptions import InvalidPriceTierError
from src.domain.value_objects.base import FrozenModel
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER

RentalUnit = Literal["day", "hour"]


class PriceTier(FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    min_units: int = Field(strict=True, ge=1, le=MAX_DATABASE_INTEGER)
    price_per_unit_minor: int = Field(strict=True, ge=1, le=MAX_DATABASE_INTEGER)

    @classmethod
    def create(cls, min_units: object, price_per_unit_minor: object) -> Self:
        try:
            return cls(
                min_units=min_units,  # type: ignore[arg-type]
                price_per_unit_minor=price_per_unit_minor,  # type: ignore[arg-type]
            )
        except ValidationError as exc:
            raise InvalidPriceTierError("Price tier is invalid") from exc


class PriceFrom(FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    amount_minor: int = Field(strict=True, ge=1, le=MAX_DATABASE_INTEGER)
    per: RentalUnit
    at_units: int = Field(strict=True, ge=1, le=MAX_DATABASE_INTEGER)
    battery_count: int = Field(strict=True, ge=0, le=MAX_DATABASE_INTEGER)
