from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from src.domain.entities.base import Entity
from src.domain.exceptions import InvalidOccupancyError
from src.domain.value_objects.time_range import TimeRange

OccupancyKind = Literal["booking", "block", "maintenance"]
OccupancyStatus = Literal["active", "released"]


@dataclass(frozen=True)
class Occupancy(Entity):
    lot_id: UUID
    kind: OccupancyKind
    period: TimeRange
    ref_id: UUID | None
    status: OccupancyStatus

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.lot_id, UUID):
            raise InvalidOccupancyError("lot_id must be a UUID")
        if self.kind not in ("booking", "block", "maintenance"):
            raise InvalidOccupancyError("kind is invalid")
        if self.status not in ("active", "released"):
            raise InvalidOccupancyError("status is invalid")
        if not isinstance(self.period, TimeRange):
            raise InvalidOccupancyError("period must be a TimeRange")
        if self.ref_id is not None and not isinstance(self.ref_id, UUID):
            raise InvalidOccupancyError("ref_id must be a UUID or None")

    @property
    def is_active(self) -> bool:
        return self.status == "active"
