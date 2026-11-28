from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from src.application.dtos.rental_dto import RentalLot
from src.application.dtos.verification_dto import AdminUserRef
from src.infrastructure.postgres.models.ticket_record import TicketCategory, TicketStatus

if TYPE_CHECKING:
    from app.models import User
    from src.infrastructure.postgres.models.lot_record import LotRecord
    from src.infrastructure.postgres.models.ticket_record import TicketRecord


class CreateTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: TicketCategory
    description: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=10, max_length=1000, pattern=r"^[^\x00]*$"
        ),
    ]
    file_ids: list[UUID] = Field(default_factory=list, max_length=3)
    photo_upload_failures: int = Field(default=0, strict=True, ge=0, le=3)

    @model_validator(mode="after")
    def validate_photos(self) -> Self:
        if len(set(self.file_ids)) != len(self.file_ids):
            raise ValueError("file_ids must be distinct")
        if len(self.file_ids) + self.photo_upload_failures > 3:
            raise ValueError("at most three photos can be submitted")
        return self


class TicketReceipt(BaseModel):
    id: UUID
    rental_id: UUID
    status: Literal["submitted"] = "submitted"
    created_at: datetime
    skipped_photo_count: int
    version: int


class Ticket(BaseModel):
    id: UUID
    rental_id: UUID
    lot: RentalLot
    user: AdminUserRef
    category: TicketCategory
    description: str
    photo_urls: list[str]
    skipped_photo_count: int
    status: TicketStatus
    admin_comment: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    version: int

    @classmethod
    def from_records(
        cls,
        record: TicketRecord,
        lot: LotRecord,
        user: User,
        *,
        photo_urls: list[str] | None = None,
    ) -> Self:
        return cls(
            id=record.id,
            rental_id=record.rental_id,
            lot=RentalLot(
                id=lot.id,
                slug=lot.slug,
                name=lot.name,
                photo_url=lot.photos[0] if lot.photos else None,
            ),
            user=AdminUserRef.model_validate(user),
            category=record.category,
            description=record.description,
            photo_urls=photo_urls or [],
            skipped_photo_count=record.skipped_photo_count,
            status=record.status,
            admin_comment=record.admin_comment,
            created_at=record.created_at,
            updated_at=record.updated_at,
            resolved_at=record.resolved_at,
            version=record.version,
        )


class TicketPage(BaseModel):
    items: list[Ticket]
    total: int
    limit: int
    offset: int
