from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app.api.audit_deps import StaffAudit
from app.api.auth_deps import require_permission, verify_csrf
from app.api.tickets import Actor, PageLimit, PageOffset, Session, no_store, ticket_with_photos
from src.application.dtos.ticket_dto import Ticket, TicketPage
from src.application.services.outbox import OutboxWriter
from src.domain.exceptions import LotUnavailableError, OccupancyConflictError
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.infrastructure.postgres.models.ticket_record import TicketStatus
from src.infrastructure.postgres.repositories.outbox_repository import OutboxRepository
from src.infrastructure.postgres.repositories.ticket_command_repository import (
    TicketCommandError,
    TicketCommandRepository,
    TicketTargetStatus,
)
from src.infrastructure.postgres.repositories.ticket_repository import TicketRepository


def _as_utc(value: datetime) -> datetime:
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise ValueError("must be representable in UTC") from exc


TicketDate = Annotated[AwareDatetime, AfterValidator(_as_utc)]
TicketComment = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=1000, pattern=r"^[^\x00]*$")
]


class TicketPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TicketTargetStatus
    version: Annotated[int, Field(strict=True, ge=1, le=MAX_DATABASE_INTEGER)]
    admin_comment: TicketComment | None = None
    put_lot_maintenance: Annotated[bool, Field(strict=True)] = False
    maintenance_until: TicketDate | None = None


router = APIRouter(
    prefix="/api/v1/admin/tickets",
    tags=["admin-tickets"],
    dependencies=[Depends(require_permission("tickets.manage")), Depends(no_store)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Permission or CSRF check failed"},
    },
)
Audit = Annotated[StaffAudit, Depends()]


def _problem(status: int, code: str, fields: dict[str, str] | None = None) -> HTTPException:
    detail: dict[str, object] = {"code": code}
    if fields is not None:
        detail["fields"] = fields
    return HTTPException(status_code=status, detail=detail)


@router.get("", operation_id="listAdminTickets")
async def list_admin_tickets(
    session: Session,
    status: TicketStatus | None = None,
    lot_id: UUID | None = None,
    rental_id: UUID | None = None,
    created_from: Annotated[TicketDate | None, Query(alias="from")] = None,
    created_to: Annotated[TicketDate | None, Query(alias="to")] = None,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> TicketPage:
    if created_from is not None and created_to is not None and created_from >= created_to:
        raise _problem(422, "validation_error", {"from": "from must be before to"})
    records, total = await TicketRepository(session).list_page(
        status=status,
        lot_id=lot_id,
        rental_id=rental_id,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return TicketPage(
        items=[Ticket.from_records(*details) for details in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{id}",
    operation_id="getAdminTicket",
    responses={
        404: {"description": "Ticket was not found"},
        503: {"description": "Photo storage is unavailable"},
    },
)
async def get_admin_ticket(id: UUID, request: Request, session: Session) -> Ticket:
    repository = TicketRepository(session)
    details = await repository.get_details(id)
    if details is None:
        raise _problem(404, "not_found")
    return await ticket_with_photos(request, repository, details)


@router.patch(
    "/{id}",
    operation_id="updateAdminTicket",
    dependencies=[Depends(verify_csrf)],
    responses={
        404: {"description": "Ticket was not found"},
        409: {"description": "stale_version, validation_error, lot_unavailable or slot_taken"},
    },
)
async def update_admin_ticket(
    id: UUID, payload: TicketPatchRequest, actor: Actor, session: Session, audit: Audit
) -> Ticket:
    if payload.put_lot_maintenance != (payload.maintenance_until is not None):
        reason = (
            "required for maintenance" if payload.put_lot_maintenance else "requires maintenance"
        )
        raise _problem(422, "validation_error", {"maintenance_until": reason})
    try:
        details, old_status = await TicketCommandRepository(session).transition(
            id,
            actor.id,
            version=payload.version,
            status=payload.status,
            admin_comment=payload.admin_comment,
            maintenance_until=payload.maintenance_until,
        )
    except TicketCommandError as exc:
        raise _problem(exc.status, exc.code, exc.fields) from exc
    except OccupancyConflictError as exc:
        raise _problem(409, "slot_taken") from exc
    except LotUnavailableError as exc:
        raise _problem(409, "lot_unavailable") from exc

    ticket, lot, user = details
    await audit.record(
        action="ticket.status_changed",
        entity_type="ticket",
        entity_id=ticket.id,
        metadata={"old_status": old_status, "new_status": ticket.status},
    )
    if payload.put_lot_maintenance:
        await audit.record(
            action="lot.status_changed",
            entity_type="lot",
            entity_id=lot.id,
            metadata={"old_status": "active", "new_status": "maintenance"},
        )
    event = "ticket.resolved.user" if ticket.status == "resolved" else "ticket.updated.user"
    await OutboxWriter(OutboxRepository(session)).enqueue(
        event_type=event, entity_id=ticket.id, user_id=user.id
    )
    return Ticket.from_records(*details)
