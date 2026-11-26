from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.domain.entities.user_account import EMAIL_RE, UserAccount

UserRole = Literal["owner", "admin", "user"]
VerificationStatus = Literal["pending", "approved", "rejected"]


class RegisterRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) > 254:
            raise ValueError("email is too long")
        if not EMAIL_RE.fullmatch(value):
            raise ValueError("invalid email")
        return value

    @field_validator("email", "password", "name", "phone")
    @classmethod
    def reject_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        return value


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) > 254:
            raise ValueError("email is too long")
        if not EMAIL_RE.fullmatch(value):
            raise ValueError("invalid email")
        return value

    @field_validator("email", "password")
    @classmethod
    def reject_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        return value


class UserDTO(BaseModel):
    id: UUID
    email: str
    name: str
    role: UserRole
    verification_status: VerificationStatus

    @classmethod
    def from_domain(cls, user: UserAccount) -> Self:
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            verification_status=user.verification_status,
        )


class LoginResponse(BaseModel):
    access_token: str
    expires_in: int
    user: UserDTO
    role: UserRole
    permissions: list[str]


class SessionDTO(BaseModel):
    user: UserDTO
    tenant_id: UUID
    role: UserRole
    permissions: list[str]
    offer_accepted: bool
