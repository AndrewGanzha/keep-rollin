from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BusyIntervalDTO(BaseModel):
    start: datetime
    end: datetime
    kind: Literal["busy", "booking", "block", "maintenance"]


class FreeWindowDTO(BaseModel):
    start: datetime
    end: datetime


class AvailabilityDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lot_id: UUID
    from_: datetime = Field(alias="from", serialization_alias="from")
    to: datetime
    busy: list[BusyIntervalDTO]
    next_free: FreeWindowDTO | None

    @classmethod
    def build(
        cls,
        *,
        lot_id: UUID,
        from_: datetime,
        to: datetime,
        busy: list[BusyIntervalDTO],
        next_free: FreeWindowDTO | None,
    ) -> Self:
        return cls(
            lot_id=lot_id,
            from_=from_,
            to=to,
            busy=busy,
            next_free=next_free,
        )


class AvailabilityWindowDTO(BaseModel):
    start: datetime
    end: datetime
    lots_free: int = Field(ge=0)


class AvailabilitySummaryDTO(BaseModel):
    lots_total: int = Field(ge=0)
    lots_free: int = Field(ge=0)
    windows: list[AvailabilityWindowDTO]
