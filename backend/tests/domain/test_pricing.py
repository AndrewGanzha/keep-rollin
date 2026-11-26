from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.domain.entities.lot_variant import LotVariant
from src.domain.exceptions import InvalidTimeRangeError
from src.domain.pricing.calculator import calculate_units, calculate_variant_price
from src.domain.pricing.errors import RentalPeriodNotAllowedError
from src.domain.value_objects.battery_count import BatteryCount
from src.domain.value_objects.duration import AllowedDurations
from src.domain.value_objects.price import PriceTier
from src.domain.value_objects.time_range import TimeRange

ALLOWED_DAILY = AllowedDurations.create([1, 3, 7, 30])


def _variant(battery_count: int, tiers: list[tuple[int, int]]) -> LotVariant:
    return LotVariant(
        id=uuid4(),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        battery_count=BatteryCount.create(battery_count),
        is_active=True,
        price_tiers=tuple(PriceTier.create(min_units, price) for min_units, price in tiers),
    )


DAILY_ONE = _variant(1, [(1, 130000), (7, 40000), (30, 40000)])
DAILY_TWO = _variant(2, [(1, 150000), (7, 50000), (30, 40000)])
HOURLY = _variant(0, [(1, 50000), (3, 40000), (24, 30000)])


@pytest.mark.parametrize(
    ("variant", "units", "expected_total", "expected_tier"),
    [
        (DAILY_ONE, 1, 130000, 1),
        (DAILY_ONE, 2, 260000, 1),
        (DAILY_ONE, 3, 280000, 7),
        (DAILY_ONE, 4, 280000, 7),
        (DAILY_ONE, 5, 280000, 7),
        (DAILY_ONE, 6, 280000, 7),
        (DAILY_ONE, 7, 280000, 7),
        (DAILY_ONE, 8, 320000, 7),
        (DAILY_ONE, 10, 400000, 7),
        (DAILY_ONE, 29, 1160000, 7),
        (DAILY_ONE, 30, 1200000, 30),
        (DAILY_ONE, 31, 1240000, 30),
        (DAILY_ONE, 60, 2400000, 30),
        (DAILY_TWO, 1, 150000, 1),
        (DAILY_TWO, 2, 300000, 1),
        (DAILY_TWO, 3, 350000, 7),
        (DAILY_TWO, 4, 350000, 7),
        (DAILY_TWO, 7, 350000, 7),
        (DAILY_TWO, 8, 400000, 7),
        (DAILY_TWO, 10, 500000, 7),
        (DAILY_TWO, 29, 1200000, 30),
        (DAILY_TWO, 30, 1200000, 30),
        (DAILY_TWO, 31, 1240000, 30),
        (DAILY_TWO, 60, 2400000, 30),
        (HOURLY, 1, 50000, 1),
        (HOURLY, 2, 100000, 1),
        (HOURLY, 3, 120000, 3),
        (HOURLY, 4, 160000, 3),
        (HOURLY, 23, 720000, 24),
        (HOURLY, 24, 720000, 24),
        (HOURLY, 25, 750000, 24),
    ],
)
def test_pricing_vectors(
    variant: LotVariant,
    units: int,
    expected_total: int,
    expected_tier: int,
) -> None:
    allowed = ALLOWED_DAILY if variant is not HOURLY else AllowedDurations.create([1, 3, 24])
    result = calculate_variant_price(variant, units=units, allowed_durations=allowed)

    assert result.units == units
    assert result.total_minor == expected_total
    assert result.tier_min_units == expected_tier


def test_units_round_up_and_cross_day_boundaries_independently_of_timezone() -> None:
    start = datetime(2026, 1, 1, 10, tzinfo=UTC)
    assert calculate_units(TimeRange(start, start + timedelta(hours=1)), "hour") == 1
    assert calculate_units(TimeRange(start, start + timedelta(hours=1, minutes=1)), "hour") == 2
    assert calculate_units(TimeRange(start, start + timedelta(hours=23)), "day") == 1
    assert calculate_units(TimeRange(start, start + timedelta(hours=24)), "day") == 1
    assert calculate_units(TimeRange(start, start + timedelta(hours=24, minutes=1)), "day") == 2

    shifted = start.astimezone(timezone(timedelta(hours=5)))
    assert calculate_units(TimeRange(shifted, shifted + timedelta(hours=24, minutes=1)), "day") == 2


def test_units_below_minimum_are_rejected() -> None:
    with pytest.raises(RentalPeriodNotAllowedError):
        calculate_variant_price(
            DAILY_ONE,
            units=6,
            allowed_durations=AllowedDurations.create([7, 30]),
        )


def test_time_range_rejects_empty_and_reversed_period() -> None:
    start = datetime(2026, 1, 1, 10, tzinfo=UTC)
    with pytest.raises(InvalidTimeRangeError):
        TimeRange(start, start)
    with pytest.raises(InvalidTimeRangeError):
        TimeRange(start + timedelta(hours=1), start)
