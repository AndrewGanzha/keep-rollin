import asyncio
import threading
import time
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.auth import _error
from app.api.auth_deps import get_password_hasher, require_permission
from src.application.repositories.i_auth_repository import IAuthRepository
from src.application.services.auth import AuthService, TokenService
from src.application.services.password_executor import run_password_work
from src.domain.entities.user_account import (
    ROLE_PERMISSIONS,
    AuthBusyError,
    UserAccount,
)
from src.infrastructure.security.secret_box import CodeHasher, SecretBox

NOW = datetime(2026, 1, 1, tzinfo=UTC)
CONTRACT_PERMISSIONS = {
    "owner": {
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
    },
    "admin": {
        "calendar.view",
        "calendar.block",
        "verification.review",
        "tickets.manage",
        "rentals.manage",
        "analytics.view",
    },
    "user": set(),
}


def _user(role: str) -> UserAccount:
    return UserAccount(
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        email=f"{role}@example.com",
        name=role.title(),
        role=role,  # type: ignore[arg-type]
        verification_status="approved",
        is_active=True,
        password_hash="hash",
        token_version=1,
    )


async def test_require_permission_accepts_owner_for_catalog_manage() -> None:
    owner = _user("owner")
    dependency = require_permission("catalog.manage")

    assert await dependency(owner) is owner


async def test_require_permission_rejects_admin_without_catalog_manage() -> None:
    dependency = require_permission("catalog.manage")

    with pytest.raises(HTTPException) as raised:
        await dependency(_user("admin"))

    assert raised.value.status_code == 403
    assert cast(object, raised.value.detail) == {"code": "forbidden_role"}


async def test_require_permission_rejects_user_without_management_permissions() -> None:
    dependency = require_permission("calendar.view")

    with pytest.raises(HTTPException) as raised:
        await dependency(_user("user"))

    assert raised.value.status_code == 403


def test_role_permissions_match_contract_matrix() -> None:
    actual = {role: set(permissions) for role, permissions in ROLE_PERMISSIONS.items()}

    assert actual == CONTRACT_PERMISSIONS


async def test_require_permission_covers_full_role_matrix() -> None:
    permissions = sorted(set().union(*CONTRACT_PERMISSIONS.values()))
    for role, allowed in CONTRACT_PERMISSIONS.items():
        user = _user(role)
        for permission in permissions:
            dependency = require_permission(permission)
            if permission in allowed:
                assert await dependency(user) is user
            else:
                with pytest.raises(HTTPException) as raised:
                    await dependency(user)
                assert raised.value.status_code == 403


class RecordingRepository:
    def __init__(self, user: UserAccount) -> None:
        self.user = user
        self.events: list[str] = []

    async def get_by_email(self, email: str) -> UserAccount:
        self.events.append("read")
        return self.user

    async def get_by_id_for_update(self, user_id: object) -> UserAccount:
        self.events.append("lock")
        return self.user

    async def commit(self) -> None:
        self.events.append("commit")

    async def create_refresh_session(self, **kwargs: object) -> object:
        self.events.append("create_refresh")
        return uuid4()


class RecordingHasher:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def hash(self, password: str) -> str:
        return "hash"

    def verify(self, password_hash: str, password: str) -> bool:
        self.events.append("verify")
        return True

    def verify_dummy(self, password: str) -> None:
        self.events.append("dummy")


class StubTokenService:
    @property
    def expires_in(self) -> int:
        return 900

    def create_access(self, **kwargs: object) -> str:
        return "access-token"

    def decode_access(self, token: str) -> object:
        raise NotImplementedError


def test_password_hasher_is_reused_across_requests() -> None:
    assert get_password_hasher() is get_password_hasher()


def test_auth_busy_error_maps_to_service_unavailable() -> None:
    error = _error(AuthBusyError("busy"))

    assert error.status_code == 503
    assert cast(object, error.detail) == {"code": "service_unavailable"}


async def test_login_releases_read_transaction_before_password_work() -> None:
    user = _user("user")
    repository = RecordingRepository(user)
    hasher = RecordingHasher(repository.events)
    service = AuthService(
        cast(IAuthRepository, repository),
        hasher,
        cast(TokenService, StubTokenService()),
        refresh_ttl_days=30,
        tenant_id=uuid4(),
        password_work_timeout_seconds=1,
        secret_box=SecretBox.from_settings("x" * 32),
        code_hasher=CodeHasher("x" * 32),
    )

    await service.login(email=user.email, password="Bike-Rider-2026!")

    assert repository.events == ["read", "commit", "verify", "lock", "create_refresh"]


async def test_password_work_returns_result() -> None:
    assert await run_password_work(lambda: 42, timeout_seconds=1) == 42


async def test_password_work_rejects_when_capacity_is_saturated() -> None:
    release = threading.Event()
    started = 0
    lock = threading.Lock()

    def blocking_operation() -> bool:
        nonlocal started
        with lock:
            started += 1
        return release.wait(5)

    first = asyncio.create_task(
        run_password_work(blocking_operation, timeout_seconds=2),
    )
    second = asyncio.create_task(
        run_password_work(blocking_operation, timeout_seconds=2),
    )
    deadline = time.monotonic() + 2
    while True:
        with lock:
            if started == 2:
                break
        if time.monotonic() >= deadline:
            raise AssertionError("password workers did not start")
        await asyncio.sleep(0.01)

    try:
        with pytest.raises(AuthBusyError):
            await run_password_work(lambda: None, timeout_seconds=0.01)
    finally:
        release.set()

    assert await first is True
    assert await second is True
