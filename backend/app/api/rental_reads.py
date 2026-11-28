from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AfterValidator, AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import get_current_user, require_permission
from app.api.deps import get_db_session
from src.application.dtos.rental_dto import (
    AdminRental,
    AdminRentalDetail,
    AdminRentalPage,
    Rental,
    RentalDetail,
    RentalPage,
)
from src.domain.entities.user_account import UserAccount
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.infrastructure.postgres.models.rental_record import RentalStatus
from src.infrastructure.postgres.repositories.rental_repository import RentalRepository


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


me_router = APIRouter(
    prefix="/api/v1/me/rentals",
    tags=["rentals"],
    dependencies=[Depends(no_store)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Tenant or session access denied"},
    },
)
admin_router = APIRouter(
    prefix="/api/v1/admin/rentals",
    tags=["admin-rentals"],
    dependencies=[Depends(require_permission("rentals.manage")), Depends(no_store)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Staff permission required"},
    },
)

Session = Annotated[AsyncSession, Depends(get_db_session)]
Actor = Annotated[UserAccount, Depends(get_current_user)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0, le=MAX_DATABASE_INTEGER)]


def _as_utc(value: datetime) -> datetime:
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise ValueError("must be representable in UTC") from exc


RentalPeriodBound = Annotated[AwareDatetime, AfterValidator(_as_utc)]


@me_router.get("", operation_id="listMyRentals")
async def list_my_rentals(
    actor: Actor,
    session: Session,
    status: RentalStatus | None = None,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> RentalPage:
    records, total = await RentalRepository(session).list_page(
        user_id=actor.id, status=status, limit=limit, offset=offset
    )
    now = datetime.now(UTC)
    return RentalPage(
        items=[Rental.from_records(rental, lot, now=now) for rental, lot, _ in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@me_router.get(
    "/{id}", operation_id="getMyRental", responses={404: {"description": "Rental was not found"}}
)
async def get_my_rental(id: UUID, actor: Actor, session: Session) -> RentalDetail:
    details = await RentalRepository(session).get_details(id, user_id=actor.id)
    if details is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    rental, lot, _ = details
    summary = Rental.from_records(rental, lot, now=datetime.now(UTC))
    return RentalDetail(**summary.model_dump(), tickets=[])


@admin_router.get("", operation_id="listAdminRentals")
async def list_admin_rentals(
    session: Session,
    status: RentalStatus | None = None,
    user_id: UUID | None = None,
    lot_id: UUID | None = None,
    period_from: Annotated[RentalPeriodBound | None, Query(alias="from")] = None,
    period_to: Annotated[RentalPeriodBound | None, Query(alias="to")] = None,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> AdminRentalPage:
    if period_from is not None and period_to is not None and period_from >= period_to:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_error", "fields": {"from": "from must be before to"}},
        )
    records, total = await RentalRepository(session).list_page(
        status=status,
        user_id=user_id,
        lot_id=lot_id,
        period_from=period_from,
        period_to=period_to,
        limit=limit,
        offset=offset,
    )
    now = datetime.now(UTC)
    return AdminRentalPage(
        items=[
            AdminRental.from_admin_records(rental, lot, user, now=now)
            for rental, lot, user in records
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@admin_router.get(
    "/{id}", operation_id="getAdminRental", responses={404: {"description": "Rental was not found"}}
)
async def get_admin_rental(id: UUID, session: Session) -> AdminRentalDetail:
    details = await RentalRepository(session).get_details(id)
    if details is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    rental, lot, user = details
    summary = AdminRental.from_admin_records(rental, lot, user, now=datetime.now(UTC))
    return AdminRentalDetail(
        **summary.model_dump(), completed_at=rental.completed_at, closed_by=rental.closed_by
    )
