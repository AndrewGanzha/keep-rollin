from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AfterValidator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from src.application.dtos.category_dto import CategoryDTO
from src.application.dtos.lot_dto import LotDTO, LotPageDTO
from src.application.handlers.category.queries.list import (
    ListCategoriesHandler,
    ListCategoriesQuery,
)
from src.application.handlers.lot.queries.get import GetLotHandler, GetLotQuery
from src.application.handlers.lot.queries.list import ListLotsHandler, ListLotsQuery
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.infrastructure.postgres.repositories.category_repository import CategoryRepository
from src.infrastructure.postgres.repositories.lot_repository import LotRepository

router = APIRouter(prefix="/api/v1/public", tags=["public-catalog"])


def validate_query(value: str | None) -> str | None:
    if value is not None and "\x00" in value:
        raise ValueError("must not contain NUL")
    return value


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
    handler: Annotated[ListCategoriesHandler, Depends(get_list_categories_handler)],
) -> list[CategoryDTO]:
    return await handler.handle(ListCategoriesQuery())


@router.get("/lots", response_model=LotPageDTO)
async def list_lots(
    handler: Annotated[ListLotsHandler, Depends(get_list_lots_handler)],
    category_id: Annotated[UUID | None, Query()] = None,
    q: Annotated[str | None, Query(), AfterValidator(validate_query)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=MAX_DATABASE_INTEGER)] = 0,
) -> LotPageDTO:
    return await handler.handle(
        ListLotsQuery(
            category_id=category_id,
            query=q,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/lots/{slug}", response_model=LotDTO)
async def get_lot(
    handler: Annotated[GetLotHandler, Depends(get_get_lot_handler)],
    slug: str,
) -> LotDTO:
    lot = await handler.handle(GetLotQuery(slug=slug))
    if lot is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return lot
