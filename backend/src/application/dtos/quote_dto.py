from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

UnavailableReason = Literal["slot_taken", "rental_period_not_allowed", "battery_unavailable"]


class QuoteVariantDTO(BaseModel):
    variant_id: UUID
    battery_count: int
    price_total_minor: int
    currency: str
    tier_min_units: int
    available: bool
    unavailable_reason: UnavailableReason | None


class QuoteDTO(BaseModel):
    lot_id: UUID
    start: datetime
    end: datetime
    units: int
    rental_unit: Literal["day", "hour"]
    variants: list[QuoteVariantDTO]
