from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.availability import get_occupancy_repository, parse_public_period
from app.api.catalog import get_lot_repository
from src.application.dtos.quote_dto import QuoteDTO
from src.application.handlers.quote.queries.get import GetLotQuoteHandler, GetLotQuoteQuery
from src.domain.pricing.errors import RentalPeriodNotAllowedError
from src.infrastructure.postgres.repositories.lot_repository import LotRepository
from src.infrastructure.postgres.repositories.occupancy_repository import OccupancyRepository

router = APIRouter(prefix="/api/v1/public", tags=["public-quote"])


def get_quote_handler(
    lot_repository: Annotated[LotRepository, Depends(get_lot_repository)],
    occupancy_repository: Annotated[OccupancyRepository, Depends(get_occupancy_repository)],
) -> GetLotQuoteHandler:
    return GetLotQuoteHandler(lot_repository, occupancy_repository)


@router.get("/lots/{slug}/quote", response_model=QuoteDTO)
async def get_lot_quote(
    handler: Annotated[GetLotQuoteHandler, Depends(get_quote_handler)],
    response: Response,
    slug: str,
    start: Annotated[datetime, Query()],
    end: Annotated[datetime, Query()],
) -> QuoteDTO:
    period = parse_public_period(start, end)
    try:
        quote = await handler.handle(GetLotQuoteQuery(slug=slug, period=period))
    except RentalPeriodNotAllowedError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "rental_period_not_allowed"},
        ) from exc
    if quote is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    response.headers["Cache-Control"] = "no-store"
    return quote
