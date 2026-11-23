from dataclasses import dataclass, field

from src.domain.entities.base import Entity
from src.domain.exceptions import CatalogDomainError
from src.domain.value_objects.battery_count import BatteryCount
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.domain.value_objects.price import PriceTier


@dataclass(frozen=True)
class LotVariant(Entity):
    battery_count: BatteryCount
    is_active: bool
    price_tiers: tuple[PriceTier, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.battery_count, BatteryCount):
            raise CatalogDomainError("battery_count must be a BatteryCount value object")
        if not isinstance(self.is_active, bool):
            raise CatalogDomainError("is_active must be a boolean")
        if not isinstance(self.price_tiers, (list, tuple)):
            raise CatalogDomainError("price_tiers must be a sequence")
        object.__setattr__(self, "price_tiers", tuple(self.price_tiers))
        if any(not isinstance(tier, PriceTier) for tier in self.price_tiers):
            raise CatalogDomainError("price_tiers must contain PriceTier value objects")

        if not self.price_tiers:
            raise CatalogDomainError("A variant needs at least one price tier")

        previous_min = 0
        previous_price = MAX_DATABASE_INTEGER
        for tier in self.price_tiers:
            if tier.min_units <= previous_min:
                raise CatalogDomainError("Price tiers must be sorted by unique min_units")
            if tier.price_per_unit_minor > previous_price:
                raise CatalogDomainError("Price per unit must not grow with duration")
            previous_min = tier.min_units
            previous_price = tier.price_per_unit_minor
