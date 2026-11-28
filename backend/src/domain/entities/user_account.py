import re
from dataclasses import dataclass
from typing import Literal

from src.domain.entities.base import Entity
from src.domain.exceptions import CatalogDomainError

UserRole = Literal["owner", "admin", "user"]
VerificationStatus = Literal["pending", "approved", "rejected"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ROLE_PERMISSIONS: dict[UserRole, tuple[str, ...]] = {
    "owner": (
        "catalog.manage",
        "settings.manage",
        "admins.manage",
        "offers.manage",
        "calendar.view",
        "calendar.block",
        "verification.review",
        "tickets.manage",
        "rentals.manage",
        "analytics.view",
        "audit.view",
    ),
    "admin": (
        "calendar.view",
        "calendar.block",
        "verification.review",
        "tickets.manage",
        "rentals.manage",
        "analytics.view",
    ),
    "user": (),
}


class AuthDomainError(CatalogDomainError):
    pass


class InvalidEmailError(AuthDomainError):
    pass


class EmailTakenError(AuthDomainError):
    pass


class InvalidCredentialsError(AuthDomainError):
    pass


class InvalidTokenError(AuthDomainError):
    pass


class TokenExpiredError(InvalidTokenError):
    pass


class SessionRevokedError(AuthDomainError):
    pass


class InactiveUserError(AuthDomainError):
    pass


class AuthBusyError(AuthDomainError):
    pass


class TenantMismatchError(AuthDomainError):
    pass


@dataclass(frozen=True)
class UserAccount(Entity):
    email: str
    name: str
    role: UserRole
    verification_status: VerificationStatus
    is_active: bool
    password_hash: str | None
    token_version: int
    phone: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.email, str) or not EMAIL_RE.fullmatch(self.email):
            raise InvalidEmailError("email is invalid")
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 120:
            raise AuthDomainError("name must be between 1 and 120 characters")
        if self.role not in ("owner", "admin", "user"):
            raise AuthDomainError("role is invalid")
        if self.verification_status not in ("pending", "approved", "rejected"):
            raise AuthDomainError("verification_status is invalid")
        if not isinstance(self.is_active, bool):
            raise AuthDomainError("is_active must be a boolean")
        if self.password_hash is not None and not isinstance(self.password_hash, str):
            raise AuthDomainError("password_hash must be a string or None")
        if (
            isinstance(self.token_version, bool)
            or not isinstance(self.token_version, int)
            or self.token_version < 1
        ):
            raise AuthDomainError("token_version must be a positive integer")
        if self.phone is not None and not isinstance(self.phone, str):
            raise AuthDomainError("phone must be a string or None")

    @property
    def permissions(self) -> tuple[str, ...]:
        return ROLE_PERMISSIONS[self.role]
