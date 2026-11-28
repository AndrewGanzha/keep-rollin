from __future__ import annotations

from datetime import datetime
from math import floor
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.application.dtos.verification_dto import AdminUserRef
from src.infrastructure.postgres.models.rental_record import RentalStatus
from src.infrastructure.postgres.models.ticket_record import TicketCategory, TicketStatus

if TYPE_CHECKING:
    from app.models import User
    from src.infrastructure.postgres.models.lot_record import LotRecord
    from src.infrastructure.postgres.models.rental_record import RentalRecord


class RentalLot(BaseModel):
    id: UUID
    slug: str
    name: str
    photo_url: str | None = Field(json_schema_extra={"format": "uri"})


class Rental(BaseModel):
    id: UUID
    lot: RentalLot
    status: RentalStatus
    start_time: datetime
    end_time: datetime
    price_minor: int
    currency: str
    remaining_seconds: int
    cancellation_deadline: datetime | None

    @staticmethod
    def from_records(rental: RentalRecord, lot: LotRecord, *, now: datetime) -> Rental:
        return Rental(
            id=rental.id,
            lot=RentalLot(
                id=lot.id,
                slug=lot.slug,
                name=lot.name,
                photo_url=lot.photos[0] if lot.photos else None,
            ),
            status=rental.status,
            start_time=rental.start_time,
            end_time=rental.end_time,
            price_minor=rental.price_minor,
            currency=rental.currency,
            remaining_seconds=floor((rental.end_time - now).total_seconds()),
            cancellation_deadline=rental.cancellation_deadline,
        )


class AdminRental(Rental):
    user: AdminUserRef
    version: int

    @staticmethod
    def from_admin_records(
        rental: RentalRecord, lot: LotRecord, user: User, *, now: datetime
    ) -> AdminRental:
        return AdminRental(
            **Rental.from_records(rental, lot, now=now).model_dump(),
            user=AdminUserRef.model_validate(user),
            version=rental.version,
        )


class RentalTicket(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: TicketCategory
    status: TicketStatus
    created_at: datetime


class RentalDetail(Rental):
    tickets: list[RentalTicket]


class AdminRentalDetail(AdminRental):
    completed_at: datetime | None
    closed_by: UUID | None


class RentalPage(BaseModel):
    items: list[Rental]
    total: int
    limit: int
    offset: int


class AdminRentalPage(BaseModel):
    items: list[AdminRental]
    total: int
    limit: int
    offset: int
