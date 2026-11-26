from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import get_current_user, verify_csrf
from app.api.deps import get_db_session
from src.application.dtos.offer_dto import (
    AcceptOfferRequest,
    OfferAcceptanceDTO,
    PublicOfferDTO,
)
from src.application.handlers.offer.commands import (
    AcceptOfferCommand,
    AcceptOfferHandler,
    ListAcceptancesHandler,
    ListAcceptancesQuery,
)
from src.application.handlers.offer.queries import (
    GetCurrentOfferHandler,
    GetCurrentOfferQuery,
)
from src.application.repositories.i_offer_repository import IOfferRepository
from src.domain.entities.offer import OfferNotActiveError, OfferNotFoundError
from src.domain.entities.user_account import UserAccount
from src.infrastructure.postgres.repositories.offer_repository import OfferRepository

public_router = APIRouter(prefix="/api/v1/public", tags=["public-offers"])
me_router = APIRouter(prefix="/api/v1/me", tags=["me-offers"])


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def get_offer_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> IOfferRepository:
    return OfferRepository(session)


def get_current_handler(
    repository: Annotated[IOfferRepository, Depends(get_offer_repository)],
) -> GetCurrentOfferHandler:
    return GetCurrentOfferHandler(repository)


def get_accept_handler(
    repository: Annotated[IOfferRepository, Depends(get_offer_repository)],
) -> AcceptOfferHandler:
    return AcceptOfferHandler(repository)


def get_list_acceptances_handler(
    repository: Annotated[IOfferRepository, Depends(get_offer_repository)],
) -> ListAcceptancesHandler:
    return ListAcceptancesHandler(repository)


def _accept_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OfferNotFoundError):
        return HTTPException(status_code=404, detail={"code": "not_found"})
    if isinstance(exc, OfferNotActiveError):
        return HTTPException(status_code=409, detail={"code": "offer_not_active"})
    raise exc


@public_router.get("/offers/current", response_model=PublicOfferDTO)
async def get_current_offer(
    handler: Annotated[GetCurrentOfferHandler, Depends(get_current_handler)],
    response: Response,
) -> PublicOfferDTO:
    offer = await handler.handle(GetCurrentOfferQuery())
    if offer is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    response.headers["Cache-Control"] = "max-age=60"
    return offer


@me_router.get(
    "/offer-acceptances",
    response_model=list[OfferAcceptanceDTO],
    dependencies=[Depends(no_store)],
)
async def list_offer_acceptances(
    user: Annotated[UserAccount, Depends(get_current_user)],
    handler: Annotated[ListAcceptancesHandler, Depends(get_list_acceptances_handler)],
) -> list[OfferAcceptanceDTO]:
    return await handler.handle(ListAcceptancesQuery(user_id=user.id))


@me_router.post(
    "/offer-acceptances",
    response_model=OfferAcceptanceDTO,
    dependencies=[Depends(verify_csrf), Depends(no_store)],
)
async def accept_offer(
    payload: AcceptOfferRequest,
    request: Request,
    user: Annotated[UserAccount, Depends(get_current_user)],
    handler: Annotated[AcceptOfferHandler, Depends(get_accept_handler)],
) -> OfferAcceptanceDTO:
    try:
        return await handler.handle(
            AcceptOfferCommand(
                user_id=user.id,
                offer_version_id=payload.offer_version_id,
                ip=request.client.host if request.client else None,
            )
        )
    except (OfferNotFoundError, OfferNotActiveError) as exc:
        raise _accept_error(exc) from exc


__all__ = ["me_router", "public_router"]
