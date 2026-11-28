from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit_deps import StaffAudit
from app.api.auth_deps import get_current_user, require_permission, verify_csrf
from app.api.deps import get_db_session
from app.api.idempotency import REPLAY_RESPONSE_HEADERS, Idempotency, IdempotencyKey
from app.api.public_period import parse_public_period
from src.application.dtos.rental_dto import AdminRental, Rental
from src.application.services.outbox import OutboxWriter
from src.domain.entities.user_account import UserAccount
from src.domain.exceptions import LotUnavailableError, OccupancyConflictError
from src.domain.pricing.errors import RentalPeriodNotAllowedError
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.repositories.outbox_repository import OutboxRepository
from src.infrastructure.postgres.repositories.rental_command_repository import (
    RentalCommandError,
    RentalCommandRepository,
)
from src.infrastructure.postgres.repositories.rental_repository import RentalRepository


class CreateRentalRequest(BaseModel):
    lot_id: UUID
    variant_id: UUID
    start_time: AwareDatetime
    end_time: AwareDatetime


StaffText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=200, pattern=r"^[^\x00]*$"),
]


class CancelAdminRentalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: StaffText


class CloseRentalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: StaffText
    lot_status: Literal["active", "maintenance"]


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Authentication required"},
    403: {"description": "Permission, eligibility or CSRF check failed"},
}
NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "Lot or rental was not found"}}

router = APIRouter(
    prefix="/api/v1",
    tags=["rentals"],
    dependencies=[Depends(verify_csrf), Depends(no_store)],
    responses=AUTH_RESPONSES,
)
admin_router = APIRouter(
    prefix="/api/v1/admin/rentals",
    tags=["admin-rentals"],
    dependencies=[
        Depends(require_permission("rentals.manage")),
        Depends(verify_csrf),
        Depends(no_store),
    ],
    responses=AUTH_RESPONSES,
)
Session = Annotated[AsyncSession, Depends(get_db_session)]
Actor = Annotated[UserAccount, Depends(get_current_user)]
Audit = Annotated[StaffAudit, Depends()]


def _problem(exc: RentalCommandError) -> HTTPException:
    details: dict[str, object] = {"code": exc.code}
    if exc.fields is not None:
        details["fields"] = exc.fields
    return HTTPException(exc.status, detail=details)


async def _record_transition(
    session: AsyncSession,
    audit: StaffAudit,
    rental: RentalRecord,
    *,
    action: str,
    event: str,
    metadata: dict[str, object] | None = None,
) -> None:
    await audit.record(action=action, entity_type="rental", entity_id=rental.id, metadata=metadata)
    await OutboxWriter(OutboxRepository(session)).enqueue(
        event_type=event, entity_id=rental.id, user_id=rental.user_id
    )


@router.post(
    "/rentals",
    operation_id="createRental",
    status_code=201,
    responses={
        **NOT_FOUND,
        201: {"headers": REPLAY_RESPONSE_HEADERS},
        409: {"description": "slot_taken, lot_unavailable or battery_unavailable"},
    },
)
async def create_rental(
    payload: CreateRentalRequest,
    response: Response,
    actor: Actor,
    session: Session,
    key: IdempotencyKey,
    idempotency: Idempotency,
    audit: Audit,
) -> Rental:
    period = parse_public_period(
        payload.start_time,
        payload.end_time,
        from_field="start_time",
        to_field="end_time",
        normalize_to_utc=True,
    )
    payload = payload.model_copy(update={"start_time": period.start, "end_time": period.end})
    cached = await idempotency.replay(actor.id, key, "rentals.create", payload, response)
    if cached is not None:
        return Rental.model_validate(cached)

    try:
        rental, lot, now = await RentalCommandRepository(session).create(
            actor.id, payload.lot_id, payload.variant_id, period
        )
    except RentalCommandError as exc:
        raise _problem(exc) from exc
    except RentalPeriodNotAllowedError as exc:
        raise HTTPException(422, detail={"code": "rental_period_not_allowed"}) from exc
    except LotUnavailableError as exc:
        raise HTTPException(409, detail={"code": "lot_unavailable"}) from exc
    except OccupancyConflictError as exc:
        raise HTTPException(409, detail={"code": "slot_taken"}) from exc

    await _record_transition(
        session, audit, rental, action="rental.booked", event="booking.confirmed"
    )
    result = Rental.from_records(rental, lot, now=now)
    await idempotency.save(actor.id, key, result)
    return result


@router.post(
    "/me/rentals/{id}/cancel",
    operation_id="cancelRental",
    responses={**NOT_FOUND, 409: {"description": "cancellation_not_allowed or rental_not_active"}},
)
async def cancel_rental(id: UUID, actor: Actor, session: Session, audit: Audit) -> Rental:
    try:
        rental, now, changed = await RentalCommandRepository(session).cancel(
            id, actor.id, own=True, reason=None
        )
    except RentalCommandError as exc:
        raise _problem(exc) from exc
    if changed:
        await _record_transition(
            session, audit, rental, action="rental.cancelled", event="booking.cancelled"
        )
    details = await RentalRepository(session).get_details(id, user_id=actor.id)
    assert details is not None
    return Rental.from_records(rental, details[1], now=now)


@admin_router.post(
    "/{id}/cancel",
    operation_id="cancelAdminRental",
    responses={**NOT_FOUND, 409: {"description": "rental_not_active"}},
)
async def cancel_admin_rental(
    id: UUID, payload: CancelAdminRentalRequest, actor: Actor, session: Session, audit: Audit
) -> AdminRental:
    try:
        rental, now, changed = await RentalCommandRepository(session).cancel(
            id, actor.id, own=False, reason=payload.reason
        )
    except RentalCommandError as exc:
        raise _problem(exc) from exc
    if changed:
        await _record_transition(
            session, audit, rental, action="rental.cancelled", event="booking.cancelled"
        )
    details = await RentalRepository(session).get_details(id)
    assert details is not None
    return AdminRental.from_admin_records(*details, now=now)


@admin_router.post(
    "/{id}/close",
    operation_id="closeAdminRental",
    responses={
        **NOT_FOUND,
        409: {"description": "rental_already_closed, lot_has_active_rental or slot_taken"},
    },
)
async def close_rental(
    id: UUID, payload: CloseRentalRequest, actor: Actor, session: Session, audit: Audit
) -> AdminRental:
    try:
        rental, now, lot_status = await RentalCommandRepository(session).close(
            id, actor.id, comment=payload.comment, lot_status=payload.lot_status
        )
    except RentalCommandError as exc:
        raise _problem(exc) from exc
    except OccupancyConflictError as exc:
        raise HTTPException(409, detail={"code": "slot_taken"}) from exc
    await _record_transition(
        session,
        audit,
        rental,
        action="rental.closed",
        event="rental.closed",
        metadata={"lot_status": lot_status},
    )
    details = await RentalRepository(session).get_details(id)
    assert details is not None
    return AdminRental.from_admin_records(*details, now=now)
