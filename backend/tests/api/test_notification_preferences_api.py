import asyncio
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.domain.entities.user_account import UserRole
from src.infrastructure.security.token_service import JwtTokenService
from tests.api.auth_helpers import JWT_SECRET, PASSWORD, enable_mfa

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")
PREFERENCES = "/api/v1/me/notification-preferences"
AUTH_SESSION = "/api/v1/auth/session"
RENTER_LOCKED = ["verification.rejected", "rental.overdue.user", "ticket.resolved.user"]
RENTER_OPTIONAL = {
    "verification.approved",
    "booking.confirmed",
    "rental.closed",
    "booking.cancelled",
    "rental.ending_soon",
    "ticket.updated.user",
}
STAFF_LOCKED = {"rental.overdue.admin", "ticket.created.admin"}


@dataclass(frozen=True)
class SeededPreferences:
    domain: str
    other_domain: str
    renter: dict[str, str]
    peer: dict[str, str]
    admin: dict[str, str]
    owner: dict[str, str]
    foreign: dict[str, str]


@pytest.fixture
def seeded() -> Iterator[SeededPreferences]:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:8]
    primary = Tenant(id=uuid4(), name="Preferences", slug=f"prefs-{suffix}")
    secondary = Tenant(id=uuid4(), name="Other tenant", slug=f"other-prefs-{suffix}")
    for tenant in (primary, secondary):
        tenant.domain = f"{tenant.slug}.test"

    users: list[User] = []

    def actor(tenant: Tenant, name: str, role: UserRole) -> dict[str, str]:
        user = User(
            id=uuid4(),
            tenant_id=tenant.id,
            name=name,
            email=f"{name}-{suffix}@example.test",
            role=role,
        )
        if role in ("admin", "owner"):
            enable_mfa(user)
        users.append(user)
        access = JwtTokenService(secret=JWT_SECRET).create_access(
            user_id=user.id, tenant_id=tenant.id, role=role, token_version=1
        )
        return {"Authorization": f"Bearer {access}"}

    value = SeededPreferences(
        domain=primary.domain,
        other_domain=secondary.domain,
        renter=actor(primary, "renter", "user"),
        peer=actor(primary, "peer", "user"),
        admin=actor(primary, "admin", "admin"),
        owner=actor(primary, "owner", "owner"),
        foreign=actor(secondary, "foreign", "user"),
    )
    engine = create_engine(DATABASE_URL)
    factory = create_session_factory(engine)

    async def create() -> None:
        try:
            async with factory() as session:
                session.add_all([primary, secondary])
                await session.flush()
                session.add_all(users)
                await session.commit()
        finally:
            await engine.dispose()

    async def cleanup() -> None:
        try:
            async with factory() as session:
                await session.execute(
                    delete(Tenant).where(Tenant.id.in_([primary.id, secondary.id]))
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(create())
    try:
        yield value
    finally:
        asyncio.run(cleanup())


def client_for(domain: str) -> TestClient:
    return TestClient(
        create_app(Settings(database_url=DATABASE_URL, app_env="test", jwt_secret=JWT_SECRET)),
        base_url=f"https://{domain}",
        headers={"Origin": f"https://{domain}", "Sec-Fetch-Site": "same-origin"},
    )


def test_defaults_for_existing_and_registered_users(seeded: SeededPreferences) -> None:
    with client_for(seeded.domain) as client:
        new = client.post(
            "/api/v1/auth/register",
            json={"email": "registered@example.test", "name": "Registered", "password": PASSWORD},
        )
        assert new.status_code == 201, new.text
        registered = {"Authorization": f"Bearer {new.json()['access_token']}"}

        for credentials in (seeded.renter, registered):
            response = client.get(PREFERENCES, headers=credentials)
            assert response.status_code == 200, response.text
            assert response.headers["Cache-Control"] == "no-store"
            assert response.json() == {
                "push_enabled": True,
                "email_by_event": dict.fromkeys(RENTER_OPTIONAL | set(RENTER_LOCKED), True),
                "locked_events": RENTER_LOCKED,
            }
            auth_session = client.get(AUTH_SESSION, headers=credentials)
            assert auth_session.status_code == 200, auth_session.text
            assert auth_session.json()["prefs_summary"] == {"push_enabled": True}


def test_partial_updates_persist_across_clients_and_auth_session(seeded: SeededPreferences) -> None:
    with client_for(seeded.domain) as client:
        before = client.put(
            PREFERENCES,
            headers=seeded.renter,
            json={"push_enabled": False, "email_by_event": {"booking.confirmed": False}},
        )
        assert before.status_code == 200, before.text
        assert before.headers["Cache-Control"] == "no-store"
        assert before.json()["push_enabled"] is False

    with client_for(seeded.domain) as other_device:
        after = other_device.put(
            PREFERENCES,
            headers=seeded.renter,
            json={"email_by_event": {"rental.ending_soon": False, "verification.rejected": True}},
        )
        assert after.status_code == 200, after.text
        unchanged = other_device.put(PREFERENCES, headers=seeded.renter, json={})
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json() == after.json()
        current = other_device.get(PREFERENCES, headers=seeded.renter).json()
        assert current == after.json()
        assert current["push_enabled"] is False
        assert current["email_by_event"]["booking.confirmed"] is False
        assert current["email_by_event"]["rental.ending_soon"] is False
        assert current["email_by_event"]["verification.rejected"] is True
        assert current["email_by_event"]["ticket.updated.user"] is True
        assert other_device.get(AUTH_SESSION, headers=seeded.renter).json()["prefs_summary"] == {
            "push_enabled": False
        }
        updated = other_device.put(PREFERENCES, headers=seeded.renter, json={"push_enabled": True})
        assert updated.status_code == 200, updated.text
        assert updated.json()["email_by_event"] == current["email_by_event"]


def test_critical_email_is_locked_and_rejects_the_whole_patch(seeded: SeededPreferences) -> None:
    with client_for(seeded.domain) as client:
        for event in RENTER_LOCKED:
            blocked = client.put(
                PREFERENCES,
                headers=seeded.renter,
                json={"push_enabled": False, "email_by_event": {event: False}},
            )
            assert blocked.status_code == 422, blocked.text
            assert blocked.headers["Content-Type"] == "application/problem+json"
            assert blocked.headers["Cache-Control"] == "no-store"
            assert blocked.json()["code"] == "critical_channel_locked"
            assert f"email_by_event.{event}" in blocked.json()["fields"]
        current = client.get(PREFERENCES, headers=seeded.renter).json()
        assert current["push_enabled"] is True
        assert all(current["email_by_event"][event] for event in RENTER_LOCKED)

        for credentials in (seeded.admin, seeded.owner):
            staff = client.get(PREFERENCES, headers=credentials)
            assert staff.status_code == 200, staff.text
            assert set(staff.json()["locked_events"]) == set(RENTER_LOCKED) | STAFF_LOCKED
            for event in STAFF_LOCKED:
                assert staff.json()["email_by_event"][event] is True
                blocked = client.put(
                    PREFERENCES, headers=credentials, json={"email_by_event": {event: False}}
                )
                assert blocked.status_code == 422, blocked.text
                assert blocked.json()["code"] == "critical_channel_locked"


def test_validate_patch_without_changing_preferences(seeded: SeededPreferences) -> None:
    invalid_payloads: tuple[dict[str, object], ...] = (
        {"push_enabled": "false"},
        {"push_enabled": None},
        {"email_by_event": None},
        {"email_by_event": {"booking.confirmed": 0}},
        {"email_by_event": {"ticket.created.admin": True}},
        {"email_by_event": {"unknown.event": True}},
        {"locked_events": []},
    )
    with client_for(seeded.domain) as client:
        for payload in invalid_payloads:
            rejected = client.put(PREFERENCES, headers=seeded.renter, json=payload)
            assert rejected.status_code == 422, rejected.text
            assert rejected.json()["code"] == "validation_error"
        assert client.get(PREFERENCES, headers=seeded.renter).json()["push_enabled"] is True


def test_authorization_csrf_and_account_isolation(seeded: SeededPreferences) -> None:
    with client_for(seeded.domain) as client:
        assert client.get(PREFERENCES).status_code == 401
        assert client.put(PREFERENCES, json={"push_enabled": False}).status_code == 401
        csrf = client.put(
            PREFERENCES,
            headers={**seeded.renter, "Origin": f"https://{seeded.other_domain}"},
            json={"push_enabled": False},
        )
        assert csrf.status_code == 403
        changed = client.put(PREFERENCES, headers=seeded.renter, json={"push_enabled": False})
        assert changed.status_code == 200, changed.text
        assert client.get(PREFERENCES, headers=seeded.peer).json()["push_enabled"] is True

    with client_for(seeded.other_domain) as other:
        assert other.get(PREFERENCES, headers=seeded.renter).json()["code"] == "tenant_mismatch"
        response = other.put(PREFERENCES, headers=seeded.renter, json={"push_enabled": False})
        assert response.status_code == 403
        assert other.get(PREFERENCES, headers=seeded.foreign).json()["push_enabled"] is True


def test_concurrent_disjoint_email_edits_are_merged(seeded: SeededPreferences) -> None:
    overlap = Barrier(2, timeout=10)

    def update(event: str) -> None:
        with client_for(seeded.domain) as client:
            overlap.wait()
            response = client.put(
                PREFERENCES, headers=seeded.renter, json={"email_by_event": {event: False}}
            )
            assert response.status_code == 200, response.text

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(update, "booking.confirmed")
        second = pool.submit(update, "ticket.updated.user")
        first.result(timeout=15)
        second.result(timeout=15)

    with client_for(seeded.domain) as client:
        current = client.get(PREFERENCES, headers=seeded.renter).json()["email_by_event"]
        assert current["booking.confirmed"] is False
        assert current["ticket.updated.user"] is False
