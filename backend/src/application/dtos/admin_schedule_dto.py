from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from src.application.dtos.battery_stock_dto import BatteryStock
from src.application.dtos.lot_dto import RentalUnit
from src.domain.entities.lot import LotStatus

ScheduleRentalStatus = Literal["booked", "active", "overdue", "completed"]


class ScheduleLot(BaseModel):
    id: UUID
    name: str
    category_id: UUID
    status: LotStatus
    battery_type: str | None
    rental_unit: RentalUnit


class _ScheduleInterval(BaseModel):
    id: UUID
    lot_id: UUID
    start_time: datetime
    end_time: datetime
    clipped_start: bool
    clipped_end: bool


class ScheduleRentalInterval(_ScheduleInterval):
    kind: Literal["rental"]
    rental_id: UUID
    status: ScheduleRentalStatus
    battery_count: int
    user_name: str


class ScheduleBlockInterval(_ScheduleInterval):
    kind: Literal["block"]
    block_id: UUID
    reason: str


ScheduleInterval = Annotated[
    ScheduleRentalInterval | ScheduleBlockInterval, Field(discriminator="kind")
]


class AdminSchedule(BaseModel):
    lots: list[ScheduleLot]
    intervals: list[ScheduleInterval]
    battery_stock: list[BatteryStock]
