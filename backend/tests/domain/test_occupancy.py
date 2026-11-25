from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.entities.occupancy import Occupancy
from src.domain.exceptions import InvalidOccupancyError, InvalidTimeRangeError
from src.domain.value_objects.time_range import TimeRange

START = datetime(2026, 1, 1, 10, tzinfo=UTC)
END = datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_time_range_requires_aware_bounds_and_start_before_end() -> None:
    with pytest.raises(InvalidTimeRangeError):
        TimeRange(datetime(2026, 1, 1, 10), END)
    with pytest.raises(InvalidTimeRangeError):
        TimeRange(START, START)
    with pytest.raises(InvalidTimeRangeError):
        TimeRange(END, START)


def test_time_range_overlap_uses_half_open_semantics() -> None:
    first = TimeRange(START, END)
    adjacent = TimeRange(END, datetime(2026, 1, 1, 14, tzinfo=UTC))
    overlapping = TimeRange(datetime(2026, 1, 1, 11, tzinfo=UTC), END)

    assert first.overlaps(overlapping) is True
    assert first.overlaps(adjacent) is False
    assert adjacent.overlaps(first) is False


def test_occupancy_validates_kind_status_and_ref() -> None:
    occupancy = Occupancy(
        id=uuid4(),
        created_at=START,
        updated_at=START,
        lot_id=uuid4(),
        kind="booking",
        period=TimeRange(START, END),
        ref_id=None,
        status="active",
    )
    assert occupancy.is_active is True

    with pytest.raises(InvalidOccupancyError):
        Occupancy(
            id=uuid4(),
            created_at=START,
            updated_at=START,
            lot_id=uuid4(),
            kind="other",  # type: ignore[arg-type]
            period=TimeRange(START, END),
            ref_id=None,
            status="active",
        )
    with pytest.raises(InvalidOccupancyError):
        Occupancy(
            id=uuid4(),
            created_at=START,
            updated_at=START,
            lot_id=uuid4(),
            kind="booking",
            period=TimeRange(START, END),
            ref_id="not-a-uuid",  # type: ignore[arg-type]
            status="active",
        )
