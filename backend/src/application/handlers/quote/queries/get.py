from dataclasses import dataclass

from src.application.dtos.quote_dto import QuoteDTO, QuoteVariantDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_lot_repository import ILotRepository
from src.application.repositories.i_occupancy_repository import IOccupancyRepository
from src.domain.exceptions import InvalidSlugError
from src.domain.pricing.calculator import calculate_units, calculate_variant_price
from src.domain.value_objects.slug import Slug
from src.domain.value_objects.time_range import TimeRange


@dataclass(frozen=True)
class GetLotQuoteQuery:
    slug: str
    period: TimeRange


class GetLotQuoteHandler(IHandler[GetLotQuoteQuery, QuoteDTO | None]):
    def __init__(
        self,
        lot_repository: ILotRepository,
        occupancy_repository: IOccupancyRepository,
    ) -> None:
        self._lot_repository = lot_repository
        self._occupancy_repository = occupancy_repository

    async def handle(self, request: GetLotQuoteQuery) -> QuoteDTO | None:
        try:
            slug = Slug.create(request.slug)
        except InvalidSlugError:
            return None

        lot = await self._lot_repository.get_active_by_slug(slug)
        if lot is None or not lot.is_bookable:
            return None

        units = calculate_units(request.period, lot.rental_unit)
        occupied = bool(
            await self._occupancy_repository.list_active(
                lot_id=lot.id,
                period=request.period,
            )
        )
        variants = []
        for variant in lot.variants:
            if not variant.is_active:
                continue
            price = calculate_variant_price(
                variant,
                units=units,
                allowed_durations=lot.allowed_durations,
            )
            variants.append(
                QuoteVariantDTO(
                    variant_id=variant.id,
                    battery_count=variant.battery_count.value,
                    price_total_minor=price.total_minor,
                    currency=lot.currency,
                    tier_min_units=price.tier_min_units,
                    available=not occupied,
                    unavailable_reason="slot_taken" if occupied else None,
                )
            )

        return QuoteDTO(
            lot_id=lot.id,
            start=request.period.start,
            end=request.period.end,
            units=units,
            rental_unit=lot.rental_unit,
            variants=variants,
        )
