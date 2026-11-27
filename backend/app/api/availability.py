from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.catalog import get_lot_repository
from app.api.deps import get_db_session
from app.api.public_period import MAX_AVAILABILITY_DAYS, parse_public_period
from src.application.dtos.availability_dto import AvailabilityDTO, AvailabilitySummaryDTO
from src.application.handlers.availability.queries.get import (
    GetLotAvailabilityHandler,
    GetLotAvailabilityQuery,
)
from src.application.handlers.availability.queries.summary import (
    GetAvailabilitySummaryHandler,
    GetAvailabilitySummaryQuery,
)
from src.infrastructure.postgres.repositories.lot_repository import LotRepository
from src.infrastructure.postgres.repositories.occupancy_repository import OccupancyRepository
from src.infrastructure.postgres.repositories.public_availability_repository import (
    PublicAvailabilityRepository,
)

router = APIRouter(prefix="/api/v1/public", tags=["public-availability"])


def get_occupancy_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OccupancyRepository:
    return OccupancyRepository(session)


def get_availability_handler(
    lot_repository: Annotated[LotRepository, Depends(get_lot_repository)],
    occupancy_repository: Annotated[OccupancyRepository, Depends(get_occupancy_repository)],
) -> GetLotAvailabilityHandler:
    return GetLotAvailabilityHandler(lot_repository, occupancy_repository)


def get_availability_summary_handler(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GetAvailabilitySummaryHandler:
    return GetAvailabilitySummaryHandler(PublicAvailabilityRepository(session))


@router.get("/availability", response_model=AvailabilitySummaryDTO)
async def get_availability_summary(
    handler: Annotated[GetAvailabilitySummaryHandler, Depends(get_availability_summary_handler)],
    response: Response,
    from_: Annotated[datetime, Query(alias="from")],
    to: Annotated[datetime, Query()],
    category_id: Annotated[UUID | None, Query()] = None,
) -> AvailabilitySummaryDTO:
    period = parse_public_period(from_, to, max_days=MAX_AVAILABILITY_DAYS, normalize_to_utc=True)
    summary = await handler.handle(
        GetAvailabilitySummaryQuery(period=period, category_id=category_id)
    )
    response.headers["Cache-Control"] = "no-store"
    return summary


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
