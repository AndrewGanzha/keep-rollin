from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel

from src.domain.entities.lot import Lot, LotStatus
from src.domain.entities.lot_variant import LotVariant
from src.domain.value_objects.price import PriceFrom, PriceTier

RentalUnit = Literal["day", "hour"]


class PriceTierDTO(BaseModel):
    min_units: int
    price_per_unit_minor: int

    @classmethod
    def from_domain(cls, tier: PriceTier) -> Self:
        return cls(
            min_units=tier.min_units,
            price_per_unit_minor=tier.price_per_unit_minor,
        )


class LotVariantDTO(BaseModel):
    id: UUID
    battery_count: int
    is_active: bool
    price_tiers: list[PriceTierDTO]

    @classmethod
    def from_domain(cls, variant: LotVariant) -> Self:
        return cls(
            id=variant.id,
            battery_count=variant.battery_count.value,
            is_active=variant.is_active,
            price_tiers=[PriceTierDTO.from_domain(tier) for tier in variant.price_tiers],
        )


class PriceFromDTO(BaseModel):
    amount_minor: int
    per: RentalUnit
    at_units: int
    battery_count: int

    @classmethod
    def from_domain(cls, price: PriceFrom) -> Self:
        return cls(
            amount_minor=price.amount_minor,
            per=price.per,
            at_units=price.at_units,
            battery_count=price.battery_count,
        )


class LotDTO(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    category_id: UUID
    photos: list[str]
    characteristics: dict[str, str | int | float]
    rental_unit: RentalUnit
    battery_type: str | None
    variants: list[LotVariantDTO]
    allowed_durations: list[int]
    price_from: PriceFromDTO | None
    currency: str
    status: LotStatus
    is_bookable: bool
    version: int

    @classmethod
    def from_domain(cls, lot: Lot) -> Self:
        price = lot.price_from()
        return cls(
            id=lot.id,
            slug=lot.slug.value,
            name=lot.name.value,
            description=lot.description or "",
            category_id=lot.category_id,
            photos=lot.photos,
            characteristics=dict(lot.characteristics),
            rental_unit=lot.rental_unit,
            battery_type=lot.battery_type,
            variants=[LotVariantDTO.from_domain(item) for item in lot.variants],
            allowed_durations=lot.allowed_durations.value,
            price_from=None if price is None else PriceFromDTO.from_domain(price),
            currency=lot.currency,
            status=lot.status,
            is_bookable=lot.is_bookable,
            version=lot.version,
        )


class LotPageDTO(BaseModel):
    items: list[LotDTO]
    total: int
    limit: int
    offset: int
