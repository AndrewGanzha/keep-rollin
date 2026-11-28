import math
from dataclasses import dataclass

from src.domain.entities.lot_variant import LotVariant
from src.domain.pricing.errors import RentalPeriodNotAllowedError
from src.domain.value_objects.duration import AllowedDurations
from src.domain.value_objects.price import RentalUnit
from src.domain.value_objects.time_range import TimeRange

UNIT_SECONDS: dict[RentalUnit, int] = {
    "day": 24 * 60 * 60,
    "hour": 60 * 60,
}


@dataclass(frozen=True)
class PriceCalculation:
    units: int
    tier_min_units: int
    total_minor: int


def calculate_units(period: TimeRange, rental_unit: RentalUnit) -> int:
    """Round the requested duration up to whole rental units."""
    return max(1, math.ceil(period.duration_seconds / UNIT_SECONDS[rental_unit]))


def calculate_variant_price(
    variant: LotVariant,
    *,
    units: int,
    allowed_durations: AllowedDurations,
) -> PriceCalculation:
    if units < allowed_durations.minimum:
        raise RentalPeriodNotAllowedError(
            f"Rental duration must be at least {allowed_durations.minimum} units"
        )

    tiers = variant.price_tiers
    base_tier = tiers[0]
    for tier in tiers:
        if tier.min_units <= units:
            base_tier = tier
        else:
            break

    total = units * base_tier.price_per_unit_minor
    winning_tier = base_tier
    for tier in tiers:
        if tier.min_units <= units:
            continue
        candidate = tier.min_units * tier.price_per_unit_minor
        if candidate < total:
            total = candidate
            winning_tier = tier

    return PriceCalculation(
        units=units,
        tier_min_units=winning_tier.min_units,
        total_minor=total,
    )
