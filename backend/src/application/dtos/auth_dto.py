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
    access_token: str | None = None
    expires_in: int
    user: UserDTO | None = None
    role: UserRole | None = None
    permissions: list[str] = Field(default_factory=list)
    mfa_required: bool = False
    mfa_setup_required: bool = False
    mfa_token: str | None = None


class MfaConfirmResponse(LoginResponse):
    recovery_codes: list[str]


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaTokenRequest(BaseModel):
    mfa_token: str = Field(min_length=20, max_length=4096)

    @field_validator("mfa_token")
    @classmethod
    def reject_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        return value


class MfaCodeRequest(MfaTokenRequest):
    code: str = Field(min_length=6, max_length=32)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip()
        if "\x00" in normalized:
            raise ValueError("NUL characters are not allowed")
        return normalized


class PasswordForgotRequest(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) > 254:
            raise ValueError("email is too long")
        if not EMAIL_RE.fullmatch(value):
            raise ValueError("invalid email")
        return value

    @field_validator("email")
    @classmethod
    def reject_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        return value


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("token", "password")
    @classmethod
    def reject_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("NUL characters are not allowed")
        return value


class MessageResponse(BaseModel):
    message: str


class SessionDTO(BaseModel):
    user: UserDTO
    tenant_id: UUID
    role: UserRole
    permissions: list[str]
    offer_accepted: bool
    mfa_enabled: bool = False
