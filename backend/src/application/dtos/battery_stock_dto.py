from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from src.domain.value_objects.limits import MAX_DATABASE_INTEGER


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _validate_battery_type(value: str) -> str:
    if value in (".", ".."):
        raise ValueError("relative path segments are invalid battery types")
    return _require_nonblank(value)


BatteryType = Annotated[
    str, Field(max_length=256, pattern=r"^[^\x00]+$"), AfterValidator(_validate_battery_type)
]
BatteryName = Annotated[str, Field(pattern=r"^[^\x00]+$"), AfterValidator(_require_nonblank)]


class BatteryStock(BaseModel):
    battery_type: str
    name: str
    quantity: int
    peak_committed: int


class UpdateBatteryStockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(strict=True, ge=0, le=MAX_DATABASE_INTEGER)


class CreateBatteryStockRequest(UpdateBatteryStockRequest):
    battery_type: BatteryType
    name: BatteryName
