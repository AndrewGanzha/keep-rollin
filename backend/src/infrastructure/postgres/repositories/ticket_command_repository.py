from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import DateTime, func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.exceptions import LotUnavailableError
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.ticket_record import TicketStatus
from src.infrastructure.postgres.repositories.occupancy_repository import insert_occupancy
from src.infrastructure.postgres.repositories.rental_repository import RentalRepository
from src.infrastructure.postgres.repositories.ticket_repository import (
    TicketDetails,
    TicketRepository,
)

TicketTargetStatus = Literal["in_progress", "resolved"]

NEXT_STATUS: dict[TicketStatus, TicketTargetStatus] = {
    "submitted": "in_progress",
    "in_progress": "resolved",
}


class TicketCommandError(Exception):
    def __init__(self, status: int, code: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.fields = fields


class TicketCommandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tickets = TicketRepository(session)

    async def transition(
        self,
        ticket_id: UUID,
        actor_id: UUID,
        *,
        version: int,
        status: TicketTargetStatus,
        admin_comment: str | None,
        maintenance_until: datetime | None,
    ) -> tuple[TicketDetails, TicketStatus]:
        details = await self._tickets.get_details(ticket_id)
        if details is None:
            raise TicketCommandError(404, "not_found")
        _, lot, user = details
        if maintenance_until is not None:
            # Match rental and calendar writers' lock order before updating occupancy.
            locked_lot = await RentalRepository(self._session).lock_lot(lot.id)
            if locked_lot is None:
                raise TicketCommandError(404, "not_found")
            lot = locked_lot
        ticket = await self._tickets.lock(ticket_id)
        if ticket is None:
            raise TicketCommandError(404, "not_found")
        if ticket.version != version:
            raise TicketCommandError(409, "stale_version")
        old_status = ticket.status
        if NEXT_STATUS.get(old_status) != status:
            raise TicketCommandError(
                409, "validation_error", {"status": "transition is not allowed"}
            )
        if status == "resolved" and (admin_comment is None or len(admin_comment) < 3):
            raise TicketCommandError(
                422, "validation_error", {"admin_comment": "at least 3 characters required"}
            )

        now = await self._session.scalar(
            select(func.clock_timestamp(type_=DateTime(timezone=True)))
        )
        assert isinstance(now, datetime)
        if maintenance_until is not None:
            if maintenance_until <= now:
                raise TicketCommandError(
                    422, "validation_error", {"maintenance_until": "must be in the future"}
                )
            if lot.status != "active":
                raise LotUnavailableError
            await insert_occupancy(
                self._session,
                OccupancyRecord(
                    tenant_id=lot.tenant_id,
                    lot_id=lot.id,
                    kind="maintenance",
                    ref_id=lot.id,
                    period=Range(now, maintenance_until, bounds="[)"),
                    status="active",
                    created_by=actor_id,
                    created_at=now,
                    updated_at=now,
                ),
            )
            lot.status = "maintenance"
            lot.version += 1
            lot.updated_at = now

        ticket.status = status
        ticket.admin_comment = admin_comment or None
        ticket.updated_at = now
        ticket.resolved_at = now if status == "resolved" else None
        ticket.version += 1
        await self._session.flush()
        return (ticket, lot, user), old_status
