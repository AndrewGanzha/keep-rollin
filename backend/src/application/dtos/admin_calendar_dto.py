from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from src.domain.entities.occupancy import Occupancy, OccupancyKind


class CalendarEventDTO(BaseModel):
    id: UUID
    lot_id: UUID
    kind: OccupancyKind
    rental_id: UUID | None
    block_id: UUID | None
    status: str
    start_time: datetime
    end_time: datetime
    reason: str | None

    @classmethod
    def from_domain(cls, occupancy: Occupancy) -> Self:
        return cls(
            id=occupancy.id,
            lot_id=occupancy.lot_id,
            kind=occupancy.kind,
            rental_id=occupancy.ref_id if occupancy.kind == "booking" else None,
            block_id=(occupancy.id if occupancy.kind in ("block", "maintenance") else None),
            status=(
                "booked"
                if occupancy.kind == "booking" and occupancy.status == "active"
                else occupancy.status
            ),
            start_time=occupancy.period.start,
            end_time=occupancy.period.end,
            reason=occupancy.reason,
        )


class LotBlockDTO(BaseModel):
    id: UUID
    lot_id: UUID
    start_time: datetime
    end_time: datetime
    reason: str
    created_by: UUID
    created_at: datetime

    @classmethod
    def from_domain(cls, occupancy: Occupancy) -> Self:
        if occupancy.reason is None or occupancy.created_by is None:
            raise ValueError("block must have reason and created_by")
        return cls(
            id=occupancy.id,
            lot_id=occupancy.lot_id,
            start_time=occupancy.period.start,
            end_time=occupancy.period.end,
            reason=occupancy.reason,
            created_by=occupancy.created_by,
            created_at=occupancy.created_at,
        )


class CreateLotBlockRequest(BaseModel):
    start_time: datetime
    end_time: datetime
    reason: str = Field(min_length=3, max_length=200)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        value = value.strip()
        if not 3 <= len(value) <= 200:
            raise ValueError("reason must be between 3 and 200 characters")
        return value

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("start_time and end_time must be timezone-aware")
        if self.start_time >= self.end_time:
            raise ValueError("end_time must be after start_time")
        if (self.end_time - self.start_time).days > 366:
            raise ValueError("block period must not exceed 366 days")
        return self
