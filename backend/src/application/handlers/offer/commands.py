from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from src.application.dtos.offer_dto import OfferAcceptanceDTO, OfferVersionDTO
from src.application.handlers.i_handler import IHandler
from src.application.repositories.i_offer_repository import IOfferRepository


@dataclass(frozen=True)
class CreateOfferCommand:
    title: str
    body: str


class CreateOfferHandler(IHandler[CreateOfferCommand, OfferVersionDTO]):
    def __init__(self, repository: IOfferRepository) -> None:
        self._repository = repository

    async def handle(self, request: CreateOfferCommand) -> OfferVersionDTO:
        offer = await self._repository.create_draft(title=request.title, body=request.body)
        return OfferVersionDTO.from_domain(offer)


@dataclass(frozen=True)
class UpdateOfferCommand:
    offer_id: UUID
    changes: Mapping[str, object]


class UpdateOfferHandler(IHandler[UpdateOfferCommand, OfferVersionDTO]):
    def __init__(self, repository: IOfferRepository) -> None:
        self._repository = repository

    async def handle(self, request: UpdateOfferCommand) -> OfferVersionDTO:
        offer = await self._repository.update_draft(request.offer_id, changes=request.changes)
        return OfferVersionDTO.from_domain(offer)


@dataclass(frozen=True)
class PublishOfferCommand:
    offer_id: UUID


class PublishOfferHandler(IHandler[PublishOfferCommand, OfferVersionDTO]):
    def __init__(self, repository: IOfferRepository) -> None:
        self._repository = repository

    async def handle(self, request: PublishOfferCommand) -> OfferVersionDTO:
        offer = await self._repository.publish(request.offer_id)
        return OfferVersionDTO.from_domain(offer)


@dataclass(frozen=True)
class AcceptOfferCommand:
    user_id: UUID
    offer_version_id: UUID
    ip: str | None


class AcceptOfferHandler(IHandler[AcceptOfferCommand, OfferAcceptanceDTO]):
    def __init__(self, repository: IOfferRepository) -> None:
        self._repository = repository

    async def handle(self, request: AcceptOfferCommand) -> OfferAcceptanceDTO:
        state = await self._repository.accept(
            user_id=request.user_id,
            offer_version_id=request.offer_version_id,
            ip=request.ip,
        )
        return OfferAcceptanceDTO.from_state(state)


@dataclass(frozen=True)
class ListAcceptancesQuery:
    user_id: UUID


class ListAcceptancesHandler(IHandler[ListAcceptancesQuery, list[OfferAcceptanceDTO]]):
    def __init__(self, repository: IOfferRepository) -> None:
        self._repository = repository

    async def handle(self, request: ListAcceptancesQuery) -> list[OfferAcceptanceDTO]:
        states = await self._repository.list_acceptances(user_id=request.user_id)
        return [OfferAcceptanceDTO.from_state(state) for state in states]
