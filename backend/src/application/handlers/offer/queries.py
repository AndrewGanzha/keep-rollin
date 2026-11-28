from dataclasses import dataclass

from src.application.dtos.offer_dto import (
    OfferPageDTO,
    OfferVersionDTO,
    PublicOfferDTO,
)
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_offer_repository import IOfferRepository


@dataclass(frozen=True)
class ListOffersQuery:
    limit: int = 20
    offset: int = 0


class ListOffersHandler(IHandler[ListOffersQuery, OfferPageDTO]):
    def __init__(self, repository: IOfferRepository) -> None:
        self._repository = repository

    async def handle(self, request: ListOffersQuery) -> OfferPageDTO:
        offers, total = await self._repository.list_versions(
            limit=request.limit,
            offset=request.offset,
        )
        return OfferPageDTO(
            items=[OfferVersionDTO.from_domain(offer) for offer in offers],
            total=total,
            limit=request.limit,
            offset=request.offset,
        )


@dataclass(frozen=True)
class GetCurrentOfferQuery:
    pass


class GetCurrentOfferHandler(IHandler[GetCurrentOfferQuery, PublicOfferDTO | None]):
    def __init__(self, repository: IOfferRepository) -> None:
        self._repository = repository

    async def handle(self, request: GetCurrentOfferQuery) -> PublicOfferDTO | None:
        offer = await self._repository.get_current()
        return None if offer is None else PublicOfferDTO.from_domain(offer)
