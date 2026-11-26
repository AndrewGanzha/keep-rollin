import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from src.domain.entities.base import Entity
from src.domain.entities.lot_variant import LotVariant
from src.domain.exceptions import CatalogDomainError
from src.domain.value_objects.duration import AllowedDurations
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.price import PriceFrom, RentalUnit
from src.domain.value_objects.slug import Slug

LotStatus = Literal["active", "archived", "maintenance", "overdue"]


@dataclass(frozen=True)
class Lot(Entity):
    slug: Slug
    name: EntityName
    description: str | None
    category_id: UUID
    photos: tuple[str, ...]
    characteristics: Mapping[str, str | int | float]
    rental_unit: RentalUnit
    battery_type: str | None
    variants: tuple[LotVariant, ...]
    allowed_durations: AllowedDurations
    status: LotStatus
    version: int
    currency: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.slug, Slug) or not isinstance(self.name, EntityName):
            raise CatalogDomainError("slug and name must be value objects")
        if not isinstance(self.category_id, UUID):
            raise CatalogDomainError("category_id must be a UUID")
        if not isinstance(self.allowed_durations, AllowedDurations):
            raise CatalogDomainError("allowed_durations must be an AllowedDurations value object")
        if self.description is not None and not isinstance(self.description, str):
            raise CatalogDomainError("description must be a string or None")
        if self.battery_type is not None and not isinstance(self.battery_type, str):
            raise CatalogDomainError("battery_type must be a string or None")
        if not isinstance(self.rental_unit, str) or self.rental_unit not in ("day", "hour"):
            raise CatalogDomainError("rental_unit must be day or hour")
        if not isinstance(self.status, str) or self.status not in (
            "active",
            "archived",
            "maintenance",
            "overdue",
        ):
            raise CatalogDomainError("status is invalid")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise CatalogDomainError("version must be a positive integer")
        if (
            not isinstance(self.currency, str)
            or len(self.currency) != 3
            or not self.currency.isascii()
            or not self.currency.isalpha()
            or not self.currency.isupper()
        ):
            raise CatalogDomainError("currency must be an uppercase three-letter code")
        if not isinstance(self.characteristics, Mapping):
            raise CatalogDomainError("characteristics must be a mapping")
        if not isinstance(self.variants, (list, tuple)):
            raise CatalogDomainError("variants must be a sequence")

        object.__setattr__(self, "photos", self._validated_photos())
        object.__setattr__(self, "variants", tuple(self.variants))
        if any(not isinstance(variant, LotVariant) for variant in self.variants):
            raise CatalogDomainError("variants must contain LotVariant entities")
        object.__setattr__(
            self,
            "characteristics",
            MappingProxyType(self._validated_characteristics()),
        )
        self._validate_variants()

    def _validated_photos(self) -> tuple[str, ...]:
        if not isinstance(self.photos, (list, tuple)):
            raise CatalogDomainError("Photo URLs must be a sequence of strings")
        photos = tuple(self.photos)
        if any(not isinstance(photo, str) for photo in photos):
            raise CatalogDomainError("Photo URLs must be strings")
        return photos

    def _validated_characteristics(self) -> dict[str, str | int | float]:
        validated: dict[str, str | int | float] = {}
        for key, value in self.characteristics.items():
            if not isinstance(key, str):
                raise CatalogDomainError("Characteristic keys must be strings")
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise CatalogDomainError("Characteristic values must be strings or numbers")
            if isinstance(value, float) and not math.isfinite(value):
                raise CatalogDomainError("Characteristic numbers must be finite")
            validated[key] = value
        return validated

    def _validate_variants(self) -> None:
        if not self.variants:
            raise CatalogDomainError("A lot needs at least one variant")

        counts: set[int] = set()
        minimum_duration = self.allowed_durations.minimum
        for variant in self.variants:
            battery_count = variant.battery_count.value
            if battery_count in counts:
                raise CatalogDomainError("Variant battery counts must be unique")
            counts.add(battery_count)

            if battery_count > 0 and not self.battery_type:
                raise CatalogDomainError("A lot with batteries needs a battery type")

            if variant.price_tiers[0].min_units != minimum_duration:
                raise CatalogDomainError("The first price tier must start at the minimum duration")

    @property
    def is_bookable(self) -> bool:
        return (
            self.status == "active"
            and any(variant.is_active for variant in self.variants)
            and self.price_from() is not None
        )

    def price_from(self) -> PriceFrom | None:
        best: tuple[int, int, int] | None = None
        for variant in self.variants:
            if not variant.is_active:
                continue
            for tier in variant.price_tiers:
                candidate = (
                    tier.price_per_unit_minor,
                    tier.min_units,
                    variant.battery_count.value,
                )
                if best is None or candidate < best:
                    best = candidate

        if best is None:
            return None

        amount, at_units, battery_count = best
        return PriceFrom(
            amount_minor=amount,
            per=self.rental_unit,
            at_units=at_units,
            battery_count=battery_count,
        )
