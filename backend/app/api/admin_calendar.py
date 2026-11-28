import re
from datetime import date, datetime, time
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BeforeValidator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit_deps import StaffAudit
from app.api.auth_deps import require_permission, verify_csrf
from app.api.deps import get_db_session
from app.api.public_period import parse_public_period
from src.application.dtos.admin_calendar_dto import (
    CalendarEventDTO,
    CreateLotBlockRequest,
    LotBlockDTO,
)
from src.application.dtos.admin_schedule_dto import AdminSchedule
from src.application.handlers.calendar.calendar import (
    CalendarQuery,
    CreateBlockCommand,
    CreateBlockHandler,
    DeleteBlockCommand,
    DeleteBlockHandler,
    GetLotCalendarHandler,
    ListCalendarHandler,
    LotCalendarQuery,
)
from src.application.repositories.i_admin_calendar_repository import (
    IAdminCalendarRepository,
)
from src.domain.entities.occupancy import BlockNotFoundError, TooManyCalendarLotsError
from src.domain.entities.user_account import UserAccount
from src.domain.exceptions import InvalidTimeRangeError, OccupancyConflictError
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.repositories.admin_calendar_repository import (
    AdminCalendarRepository,
)
from src.infrastructure.postgres.repositories.admin_schedule_repository import (
    AdminScheduleRepository,
)

MAX_CALENDAR_DAYS = 90
CalendarStatusFilter = Literal["booked", "active", "overdue", "completed", "cancelled", "released"]

router = APIRouter(prefix="/api/v1/admin", tags=["admin-calendar"])


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _require_date_key(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("must be in YYYY-MM-DD format")
    return value


ScheduleDate = Annotated[date, BeforeValidator(_require_date_key)]


def get_calendar_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> IAdminCalendarRepository:
    return AdminCalendarRepository(session)


def get_schedule_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminScheduleRepository:
    return AdminScheduleRepository(session)


def get_list_handler(
    repository: Annotated[IAdminCalendarRepository, Depends(get_calendar_repository)],
) -> ListCalendarHandler:
    return ListCalendarHandler(repository)


def get_lot_handler(
    repository: Annotated[IAdminCalendarRepository, Depends(get_calendar_repository)],
) -> GetLotCalendarHandler:
    return GetLotCalendarHandler(repository)


def get_create_block_handler(
    repository: Annotated[IAdminCalendarRepository, Depends(get_calendar_repository)],
) -> CreateBlockHandler:
    return CreateBlockHandler(repository)


def get_delete_block_handler(
    repository: Annotated[IAdminCalendarRepository, Depends(get_calendar_repository)],
) -> DeleteBlockHandler:
    return DeleteBlockHandler(repository)


def _period(from_: datetime, to: datetime) -> TimeRange:
    try:
        period = TimeRange(start=from_, end=to)
    except InvalidTimeRangeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_error", "fields": {"from": str(exc)}},
        ) from exc
    if period.duration_seconds > MAX_CALENDAR_DAYS * 86400:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {"to": f"calendar period must not exceed {MAX_CALENDAR_DAYS} days"},
            },
        )
    return period


def _calendar_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TooManyCalendarLotsError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {"period": "calendar filter matches more than 200 lots"},
            },
        )
    if isinstance(exc, OccupancyConflictError):
        return HTTPException(status_code=409, detail={"code": "slot_taken"})
    if isinstance(exc, BlockNotFoundError):
        return HTTPException(status_code=404, detail={"code": "not_found"})
    if isinstance(exc, InvalidTimeRangeError):
        return HTTPException(
            status_code=422,
            detail={"code": "validation_error", "fields": {"start_time": str(exc)}},
        )
    raise exc


@router.get(
    "/calendar",
    response_model=list[CalendarEventDTO],
    dependencies=[
        Depends(require_permission("calendar.view")),
        Depends(no_store),
    ],
)
async def get_calendar(
    handler: Annotated[ListCalendarHandler, Depends(get_list_handler)],
    from_: Annotated[datetime, Query(alias="from")],
    to: datetime,
    category_id: Annotated[UUID | None, Query()] = None,
    lot_id: Annotated[UUID | None, Query()] = None,
    status_filter: Annotated[CalendarStatusFilter | None, Query(alias="status")] = None,
) -> list[CalendarEventDTO]:
    try:
        return await handler.handle(
            CalendarQuery(
                period=_period(from_, to),
                category_id=category_id,
                lot_id=lot_id,
                status=status_filter,
            )
        )
    except TooManyCalendarLotsError as exc:
        raise _calendar_error(exc) from exc


@router.get(
    "/schedule",
    operation_id="getAdminSchedule",
    response_model=AdminSchedule,
    dependencies=[Depends(require_permission("calendar.view")), Depends(no_store)],
    responses={
        200: {"headers": {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}},
        401: {"description": "Authentication required"},
        403: {"description": "Calendar access required"},
        422: {"description": "Invalid category or date range"},
    },
)
async def get_admin_schedule(
    repository: Annotated[AdminScheduleRepository, Depends(get_schedule_repository)],
    from_: Annotated[ScheduleDate, Query(alias="from", description="First tenant-local date")],
    to: Annotated[ScheduleDate, Query(description="Exclusive tenant-local date")],
    category_id: Annotated[UUID | None, Query()] = None,
) -> AdminSchedule:
    if not 0 < (to - from_).days <= MAX_CALENDAR_DAYS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {"to": f"range must cover 1 to {MAX_CALENDAR_DAYS} calendar days"},
            },
        )
    timezone_name = await repository.tenant_timezone()
    if timezone_name is None:
        raise HTTPException(status_code=404, detail={"code": "tenant_not_found"})
    timezone = ZoneInfo(timezone_name)
    period = parse_public_period(
        datetime.combine(from_, time.min, tzinfo=timezone),
        datetime.combine(to, time.min, tzinfo=timezone),
        normalize_to_utc=True,
    )
    return await repository.get_schedule(period=period, category_id=category_id)


@router.get(
    "/lots/{lot_id}/calendar",
    response_model=list[CalendarEventDTO],
    dependencies=[
        Depends(require_permission("calendar.view")),
        Depends(no_store),
    ],
)
async def get_lot_calendar(
    lot_id: UUID,
    handler: Annotated[GetLotCalendarHandler, Depends(get_lot_handler)],
    from_: Annotated[datetime, Query(alias="from")],
    to: datetime,
) -> list[CalendarEventDTO]:
    events = await handler.handle(LotCalendarQuery(lot_id=lot_id, period=_period(from_, to)))
    if events is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return events


@router.post(
    "/lots/{lot_id}/blocks",
    response_model=LotBlockDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(verify_csrf),
        Depends(no_store),
    ],
)
async def create_block(
    lot_id: UUID,
    payload: CreateLotBlockRequest,
    user: Annotated[UserAccount, Depends(require_permission("calendar.block"))],
    handler: Annotated[CreateBlockHandler, Depends(get_create_block_handler)],
    audit: Annotated[StaffAudit, Depends()],
) -> LotBlockDTO:
    try:
        block = await handler.handle(
            CreateBlockCommand(
                lot_id=lot_id,
                period=TimeRange(start=payload.start_time, end=payload.end_time),
                reason=payload.reason,
                created_by=user.id,
            )
        )
    except (OccupancyConflictError, BlockNotFoundError, InvalidTimeRangeError) as exc:
        raise _calendar_error(exc) from exc
    await audit.record(action="lot.blocked", entity_type="lot_block", entity_id=block.id)
    return block


@router.delete(
    "/lots/{lot_id}/blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(require_permission("calendar.block")),
        Depends(verify_csrf),
        Depends(no_store),
    ],
)
async def delete_block(
    lot_id: UUID,
    block_id: UUID,
    handler: Annotated[DeleteBlockHandler, Depends(get_delete_block_handler)],
    audit: Annotated[StaffAudit, Depends()],
) -> Response:
    try:
        released = await handler.handle(DeleteBlockCommand(lot_id=lot_id, block_id=block_id))
    except BlockNotFoundError as exc:
        raise _calendar_error(exc) from exc
    if released:
        await audit.record(action="lot.unblocked", entity_type="lot_block", entity_id=block_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
