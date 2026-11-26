from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.application.repositories.i_offer_repository import OfferAcceptanceState
from src.domain.entities.offer import OfferStatus, OfferVersion


class OfferVersionDTO(BaseModel):
    id: UUID
    version: int
    title: str
    body: str
    status: OfferStatus
    published_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, offer: OfferVersion) -> Self:
        return cls(
            id=offer.id,
            version=offer.version,
            title=offer.title,
            body=offer.body,
            status=offer.status,
            published_at=offer.published_at.isoformat() if offer.published_at else None,
            created_at=offer.created_at.isoformat(),
            updated_at=offer.updated_at.isoformat(),
        )


class OfferPageDTO(BaseModel):
    items: list[OfferVersionDTO]
    total: int
    limit: int
    offset: int


class PublicOfferDTO(BaseModel):
    id: UUID
    version: int
    title: str
    body: str
    published_at: str

    @classmethod
    def from_domain(cls, offer: OfferVersion) -> Self:
        if offer.published_at is None:
            raise ValueError("active offer must have published_at")
        return cls(
            id=offer.id,
            version=offer.version,
            title=offer.title,
            body=offer.body,
            published_at=offer.published_at.isoformat(),
        )


class CreateOfferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)

    @field_validator("title", "body")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class UpdateOfferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=20000)

    @field_validator("title", "body")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        for field in ("title", "body"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self


class AcceptOfferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_version_id: UUID


class OfferAcceptanceDTO(BaseModel):
    id: UUID
    offer_version_id: UUID
    version: int
    accepted_at: str
    ip: str | None

    @classmethod
    def from_state(cls, state: OfferAcceptanceState) -> Self:
        return cls(
            id=state.acceptance.id,
            offer_version_id=state.acceptance.offer_version_id,
            version=state.version_number,
            accepted_at=state.acceptance.accepted_at.isoformat(),
            ip=state.acceptance.ip,
        )
