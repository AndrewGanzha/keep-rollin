from __future__ import annotations

from datetime import datetime
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.entities.user_account import EMAIL_RE
from src.infrastructure.postgres.repositories.admin_user_repository import AdminUserInfo

AdminRole = Literal["owner", "admin", "user"]


class AdminUserDTO(BaseModel):
    id: UUID
    email: str
    name: str
    role: AdminRole
    is_active: bool
    mfa_enabled: bool
    created_at: datetime

    @classmethod
    def from_info(cls, info: AdminUserInfo) -> Self:
        return cls(
            id=info.id,
            email=info.email,
            name=info.name,
            role=cast(AdminRole, info.role),
            is_active=info.is_active,
            mfa_enabled=info.mfa_enabled,
            created_at=info.created_at,
        )


class AdminUserListDTO(BaseModel):
    items: list[AdminUserDTO]
    total: int
    limit: int
    offset: int


class AdminUserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    mfa_code: str | None = Field(default=None, max_length=32)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) > 254:
            raise ValueError("email is too long")
        if not EMAIL_RE.fullmatch(value):
            raise ValueError("invalid email")
        return value

    @field_validator("email", "name", "password", "mfa_code")
    @classmethod
    def reject_nul(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        return value
