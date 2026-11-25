from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.entities.user_account import (
    ROLE_PERMISSIONS,
    AuthDomainError,
    InvalidEmailError,
    UserAccount,
)
from src.domain.policies.password_policy import (
    PasswordCompromisedError,
    ensure_password_not_compromised,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _user(role: str = "user", email: str = "rider@example.com") -> UserAccount:
    return UserAccount(
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        email=email,
        name="Rider",
        role=role,  # type: ignore[arg-type]
        verification_status="pending",
        is_active=True,
        password_hash="hash",
        token_version=1,
    )


def test_user_account_permissions_follow_role_matrix() -> None:
    assert "catalog.manage" in ROLE_PERMISSIONS["owner"]
    assert "audit.view" in ROLE_PERMISSIONS["owner"]
    assert "catalog.manage" not in ROLE_PERMISSIONS["admin"]
    assert "calendar.view" in ROLE_PERMISSIONS["admin"]
    assert ROLE_PERMISSIONS["user"] == ()
    assert _user("owner").permissions == ROLE_PERMISSIONS["owner"]


def test_compromised_password_policy_is_case_insensitive() -> None:
    with pytest.raises(PasswordCompromisedError):
        ensure_password_not_compromised("Password123")
    ensure_password_not_compromised("Bike-Rider-2026!")


def test_user_account_validates_email_role_and_token_version() -> None:
    with pytest.raises(InvalidEmailError):
        _user(email="not-email")
    with pytest.raises(AuthDomainError):
        _user(role="superuser")
    with pytest.raises(AuthDomainError):
        UserAccount(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            email="rider@example.com",
            name="Rider",
            role="user",
            verification_status="pending",
            is_active=True,
            password_hash="hash",
            token_version=0,
        )
