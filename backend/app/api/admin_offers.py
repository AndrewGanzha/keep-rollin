from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import require_permission, verify_csrf
from app.api.deps import get_db_session
from src.application.dtos.offer_dto import (
    CreateOfferRequest,
    OfferPageDTO,
    OfferVersionDTO,
    UpdateOfferRequest,
)
from src.application.handlers.offer.commands import (
    CreateOfferCommand,
    CreateOfferHandler,
    PublishOfferCommand,
    PublishOfferHandler,
    UpdateOfferCommand,
    UpdateOfferHandler,
)
from src.application.handlers.offer.queries import ListOffersHandler, ListOffersQuery
from src.application.repositories.i_offer_repository import IOfferRepository
from src.domain.entities.offer import (
    OfferNotEditableError,
    OfferNotFoundError,
)
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.infrastructure.postgres.repositories.offer_repository import OfferRepository


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/admin/offers",
    tags=["admin-offers"],
    dependencies=[
        Depends(require_permission("offers.manage")),
        Depends(no_store),
    ],
)


def get_offer_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> IOfferRepository:
    return OfferRepository(session)


def get_list_handler(
    repository: Annotated[IOfferRepository, Depends(get_offer_repository)],
) -> ListOffersHandler:
    return ListOffersHandler(repository)


def get_create_handler(
    repository: Annotated[IOfferRepository, Depends(get_offer_repository)],
) -> CreateOfferHandler:
    return CreateOfferHandler(repository)


def get_update_handler(
    repository: Annotated[IOfferRepository, Depends(get_offer_repository)],
) -> UpdateOfferHandler:
    return UpdateOfferHandler(repository)


def get_publish_handler(
    repository: Annotated[IOfferRepository, Depends(get_offer_repository)],
) -> PublishOfferHandler:
    return PublishOfferHandler(repository)


def _offer_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OfferNotFoundError):
        return HTTPException(status_code=404, detail={"code": "not_found"})
    if isinstance(exc, OfferNotEditableError):
        return HTTPException(status_code=409, detail={"code": "offer_not_editable"})
    raise exc


@router.get("", response_model=OfferPageDTO)
async def list_offers(
    handler: Annotated[ListOffersHandler, Depends(get_list_handler)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=MAX_DATABASE_INTEGER)] = 0,
) -> OfferPageDTO:
    return await handler.handle(ListOffersQuery(limit=limit, offset=offset))


@router.post(
    "",
    response_model=OfferVersionDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
async def create_offer(
    payload: CreateOfferRequest,
    handler: Annotated[CreateOfferHandler, Depends(get_create_handler)],
) -> OfferVersionDTO:
    return await handler.handle(CreateOfferCommand(title=payload.title, body=payload.body))


@router.patch(
    "/{offer_id}",
    response_model=OfferVersionDTO,
    dependencies=[Depends(verify_csrf)],
)
async def update_offer(
    offer_id: UUID,
    payload: UpdateOfferRequest,
    handler: Annotated[UpdateOfferHandler, Depends(get_update_handler)],
) -> OfferVersionDTO:
    try:
        return await handler.handle(
            UpdateOfferCommand(
                offer_id=offer_id,
                changes=payload.model_dump(exclude_unset=True),
            )
        )
    except (OfferNotFoundError, OfferNotEditableError) as exc:
        raise _offer_error(exc) from exc


@router.post(
    "/{offer_id}/publish",
    response_model=OfferVersionDTO,
    dependencies=[Depends(verify_csrf)],
)
async def publish_offer(
    offer_id: UUID,
    handler: Annotated[PublishOfferHandler, Depends(get_publish_handler)],
) -> OfferVersionDTO:
    try:
        return await handler.handle(PublishOfferCommand(offer_id=offer_id))
    except (OfferNotFoundError, OfferNotEditableError) as exc:
        raise _offer_error(exc) from exc


__all__ = ["router"]
