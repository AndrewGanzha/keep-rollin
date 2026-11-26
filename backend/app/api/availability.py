from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.catalog import get_lot_repository
from app.api.deps import get_db_session
from src.application.dtos.availability_dto import AvailabilityDTO
from src.application.handlers.availability.queries.get import (
    GetLotAvailabilityHandler,
    GetLotAvailabilityQuery,
)
from src.domain.exceptions import InvalidTimeRangeError
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.repositories.lot_repository import LotRepository
from src.infrastructure.postgres.repositories.occupancy_repository import OccupancyRepository

router = APIRouter(prefix="/api/v1/public", tags=["public-availability"])
MAX_AVAILABILITY_DAYS = 90


def get_occupancy_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OccupancyRepository:
    return OccupancyRepository(session)


def get_availability_handler(
    lot_repository: Annotated[LotRepository, Depends(get_lot_repository)],
    occupancy_repository: Annotated[OccupancyRepository, Depends(get_occupancy_repository)],
) -> GetLotAvailabilityHandler:
    return GetLotAvailabilityHandler(lot_repository, occupancy_repository)


def parse_public_period(
    from_: datetime,
    to: datetime,
    *,
    max_days: int | None = None,
) -> TimeRange:
    if (
        from_.tzinfo is None
        or from_.utcoffset() is None
        or to.tzinfo is None
        or to.utcoffset() is None
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {"from": "must be timezone-aware"},
            },
        )
    try:
        period = TimeRange(from_, to)
    except InvalidTimeRangeError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {"to": "must be after from"},
            },
        ) from exc
    if max_days is not None and period.duration_seconds > max_days * 86400:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {"to": f"range must not exceed {max_days} days"},
            },
        )
    return period


@router.get("/lots/{slug}/availability", response_model=AvailabilityDTO)
async def get_lot_availability(
    handler: Annotated[GetLotAvailabilityHandler, Depends(get_availability_handler)],
    response: Response,
    slug: str,
    from_: Annotated[datetime, Query(alias="from")],
    to: Annotated[datetime, Query()],
) -> AvailabilityDTO:
    period = parse_public_period(from_, to, max_days=MAX_AVAILABILITY_DAYS)
    availability = await handler.handle(GetLotAvailabilityQuery(slug=slug, period=period))
    if availability is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    response.headers["Cache-Control"] = "no-store"
    return availability


__all__ = ["MAX_AVAILABILITY_DAYS", "parse_public_period", "router"]
