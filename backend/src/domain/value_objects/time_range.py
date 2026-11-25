from dataclasses import dataclass
from datetime import datetime

from src.domain.exceptions import InvalidTimeRangeError


@dataclass(frozen=True)
class TimeRange:
    """Half-open time interval [start, end) in timezone-aware time."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.start, datetime) or not isinstance(self.end, datetime):
            raise InvalidTimeRangeError("Time range bounds must be datetimes")
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise InvalidTimeRangeError("Time range start must be timezone-aware")
        if self.end.tzinfo is None or self.end.utcoffset() is None:
            raise InvalidTimeRangeError("Time range end must be timezone-aware")
        if self.start >= self.end:
            raise InvalidTimeRangeError("Time range end must be after start")

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def overlaps(self, other: "TimeRange") -> bool:
        return self.start < other.end and other.start < self.end
