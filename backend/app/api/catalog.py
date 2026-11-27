from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AfterValidator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.catalog_cache import CATALOG_CACHE_RESPONSES, IfNoneMatch, catalog_cache_response
from app.api.deps import get_db_session
from app.api.public_period import MAX_AVAILABILITY_DAYS, parse_public_period
from src.application.dtos.category_dto import CategoryDTO
from src.application.dtos.lot_dto import LotDTO, LotPageDTO
from src.application.handlers.category.queries.list import (
    ListCategoriesHandler,
    ListCategoriesQuery,
)
from src.application.handlers.lot.queries.get import GetLotHandler, GetLotQuery
from src.application.handlers.lot.queries.list import ListLotsHandler, ListLotsQuery
from src.application.repositories.i_lot_repository import InvalidLotCharacteristicFilter, LotSort
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.domain.value_objects.slug import SLUG_RE
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.repositories.category_repository import CategoryRepository
from src.infrastructure.postgres.repositories.lot_repository import LotRepository

router = APIRouter(
    prefix="/api/v1/public",
    tags=["public-catalog"],
    responses=CATALOG_CACHE_RESPONSES,
)


def validate_query(value: str | None) -> str | None:
    if value is not None and "\x00" in value:
        raise ValueError("must not contain NUL")
    return value


def _filter_error(field: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "validation_error", "fields": {field: message}},
    )


LOT_LIST_QUERY_FIELDS = frozenset(
    {"category_id", "q", "limit", "offset", "available_from", "available_to", "sort"}
)


def _characteristic_filters(request: Request) -> tuple[tuple[str, str], ...]:
    filters: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key in LOT_LIST_QUERY_FIELDS:
            continue
        if not key.startswith("char_"):
            raise _filter_error(key, "unknown filter")
        code = key.removeprefix("char_")
        if len(code) > 80 or SLUG_RE.fullmatch(code) is None:
            raise _filter_error(key, "unknown characteristic")
        if code in filters:
            raise _filter_error(key, "duplicate characteristic filter")
        if not value.strip() or "\x00" in value:
            raise _filter_error(key, "invalid characteristic value")
        filters[code] = value
    return tuple(filters.items())


def _available_period(
    available_from: datetime | None, available_to: datetime | None
) -> TimeRange | None:
    if available_from is None and available_to is None:
        return None
    if available_from is None:
        raise _filter_error("available_from", "required with available_to")
    if available_to is None:
        raise _filter_error("available_to", "required with available_from")
    return parse_public_period(
        available_from,
        available_to,
        max_days=MAX_AVAILABILITY_DAYS,
        from_field="available_from",
        to_field="available_to",
        normalize_to_utc=True,
    )


def get_category_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CategoryRepository:
    return CategoryRepository(session)


def get_lot_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LotRepository:
    return LotRepository(session)


def get_list_categories_handler(
    repository: Annotated[CategoryRepository, Depends(get_category_repository)],
) -> ListCategoriesHandler:
    return ListCategoriesHandler(repository)


def get_list_lots_handler(
    repository: Annotated[LotRepository, Depends(get_lot_repository)],
) -> ListLotsHandler:
    return ListLotsHandler(repository)


def get_get_lot_handler(
    repository: Annotated[LotRepository, Depends(get_lot_repository)],
) -> GetLotHandler:
    return GetLotHandler(repository)


@router.get("/categories", response_model=list[CategoryDTO])
async def list_categories(
    request: Request,
    response: Response,
    handler: Annotated[ListCategoriesHandler, Depends(get_list_categories_handler)],
    if_none_match: IfNoneMatch = None,
) -> list[CategoryDTO] | Response:
    categories = await handler.handle(ListCategoriesQuery())
    return (
        catalog_cache_response(request.state.tenant_id, if_none_match, response, categories)
        or categories
    )


@router.get(
    "/lots",
    response_model=LotPageDTO,
    description=(
        "Filter characteristics by equality with char_<code>. Numeric values compare by value. "
        "Text and select values compare exactly, and select values must be defined options. "
        "Availability bounds are both required when filtering by period."
    ),
)
async def list_lots(
    request: Request,
    response: Response,
    handler: Annotated[ListLotsHandler, Depends(get_list_lots_handler)],
    category_id: Annotated[UUID | None, Query()] = None,
    q: Annotated[str | None, Query(), AfterValidator(validate_query)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=MAX_DATABASE_INTEGER)] = 0,
    available_from: Annotated[datetime | None, Query()] = None,
    available_to: Annotated[datetime | None, Query()] = None,
    sort: Annotated[LotSort, Query()] = "newest",
    if_none_match: IfNoneMatch = None,
) -> LotPageDTO | Response:
    try:
        lots = await handler.handle(
            ListLotsQuery(
                category_id=category_id,
                query=q,
                limit=limit,
                offset=offset,
                characteristics=_characteristic_filters(request),
                available_period=_available_period(available_from, available_to),
                sort=sort,
            )
        )
    except InvalidLotCharacteristicFilter as exc:
        raise _filter_error(f"char_{exc.code}", str(exc)) from exc
    return catalog_cache_response(request.state.tenant_id, if_none_match, response, lots) or lots


@router.get("/lots/{slug}", response_model=LotDTO)
async def get_lot(
    request: Request,
    response: Response,
    handler: Annotated[GetLotHandler, Depends(get_get_lot_handler)],
    slug: str,
    if_none_match: IfNoneMatch = None,
) -> LotDTO | Response:
    lot = await handler.handle(GetLotQuery(slug=slug))
    if lot is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return catalog_cache_response(request.state.tenant_id, if_none_match, response, lot) or lot
