from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.security.password_hasher import Argon2PasswordHasher
from tests.api.auth_helpers import enable_mfa, login_with_mfa

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
JWT_SECRET = "test-secret-keep-rollin-0123456789abcdef"
PASSWORD = "Bike-Rider-2026!"


@dataclass(frozen=True)
class SeededSettings:
    domain_a: str
    domain_b: str
    tenant_a: UUID
    tenant_b: UUID
    owner_email: str
    admin_email: str
    user_email: str


def seed_settings() -> SeededSettings:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    hasher = Argon2PasswordHasher()
    tenant_a = Tenant(
        id=uuid4(),
        name="Settings API A",
        slug=f"settings-api-a-{suffix}",
        domain=f"settings-api-a-{suffix}.test",
        subdomain=f"settings-api-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Settings API B",
        slug=f"settings-api-b-{suffix}",
        domain=f"settings-api-b-{suffix}.test",
        subdomain=f"settings-api-b-{suffix}",
    )
    password_hash = hasher.hash(PASSWORD)
    users = [
        User(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"{role}-{suffix}@example.com",
            name=role.title(),
            role=role,
            password_hash=password_hash,
            verification_status="approved",
            is_active=True,
            token_version=1,
        )
        for role in ("owner", "admin", "user")
    ]
    for user in users:
        if user.role in ("owner", "admin"):
            enable_mfa(user)

    async def seed() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add_all([tenant_a, tenant_b])
                await session.flush()
                session.add_all(users)
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return SeededSettings(
        domain_a=tenant_a.domain,
        domain_b=tenant_b.domain,
        tenant_a=tenant_a.id,
        tenant_b=tenant_b.id,
        owner_email=users[0].email,
        admin_email=users[1].email,
        user_email=users[2].email,
    )


def cleanup_settings(tenant_ids: tuple[UUID, UUID]) -> None:
    assert DATABASE_URL is not None

    async def cleanup() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(
                    delete(AuditLogRecord).where(AuditLogRecord.tenant_id.in_(tenant_ids))
                )
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(cleanup())


@pytest.fixture
def seeded() -> Iterator[SeededSettings]:
    value = seed_settings()
    try:
        yield value
    finally:
        cleanup_settings((value.tenant_a, value.tenant_b))


def client_for(domain: str, *, browser_headers: bool = True) -> TestClient:
    assert DATABASE_URL is not None
    settings = Settings(
        database_url=DATABASE_URL,
        app_env="test",
        platform_domain="platform.test",
        allow_tenant_header=True,
        database_role="keep_rollin_app",
        jwt_secret=JWT_SECRET,
        refresh_cookie_secure=True,
    )
    headers = (
        {
            "Sec-Fetch-Site": "same-origin",
            "Origin": f"https://{domain}",
        }
        if browser_headers
        else None
    )
    return TestClient(create_app(settings), base_url=f"https://{domain}", headers=headers)


def login(client: TestClient, email: str) -> str:
    payload = login_with_mfa(client, email)
    return str(payload["access_token"])


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_owner_settings_update_and_public_reflection(seeded: SeededSettings) -> None:
    with client_for(seeded.domain_a) as client:
        token = login(client, seeded.owner_email)
        headers = auth(token)

        before = client.get("/api/v1/public/tenant")
        assert before.status_code == 200
        assert before.json()["policies"]["booking_horizon_days"] == 60

        current = client.get("/api/v1/admin/settings", headers=headers)
        assert current.status_code == 200
        assert current.headers["Cache-Control"] == "no-store"
        assert current.json()["version"] == 1

        updated = client.patch(
            "/api/v1/admin/settings",
            headers=headers,
            json={
                "version": 1,
                "timezone": "Asia/Yekaterinburg",
                "currency": "USD",
                "primary_color": "#123abc",
                "logo_url": "https://cdn.example/logo.png",
                "policies": {
                    "booking_horizon_days": 90,
                    "lot_photos_max": 12,
                },
            },
        )
        assert updated.status_code == 200
        payload = updated.json()
        assert payload["version"] == 2
        assert payload["timezone"] == "Asia/Yekaterinburg"
        assert payload["currency"] == "USD"
        assert payload["policies"]["booking_horizon_days"] == 90
        assert payload["policies"]["lot_photos_max"] == 12
        assert payload["policies"]["max_rental_days"] == 30

        after = client.get("/api/v1/public/tenant")
        assert after.status_code == 200
        public = after.json()
        assert public["timezone"] == "Asia/Yekaterinburg"
        assert public["currency"] == "USD"
        assert public["primary_color"] == "#123abc"
        assert public["logo_url"] == "https://cdn.example/logo.png"
        assert public["policies"]["booking_horizon_days"] == 90
        assert public["policies"]["lot_photos_max"] == 12

        second_update = client.patch(
            "/api/v1/admin/settings",
            headers=headers,
            json={
                "version": 2,
                "currency": "EUR",
                "policies": {"max_rental_days": 20},
            },
        )
        assert second_update.status_code == 200
        assert second_update.json()["version"] == 3
        assert second_update.json()["currency"] == "EUR"
        assert second_update.json()["policies"]["max_rental_days"] == 20
        assert second_update.json()["policies"]["booking_horizon_days"] == 90

        public_second = client.get("/api/v1/public/tenant").json()
        assert public_second["currency"] == "EUR"
        assert public_second["policies"]["max_rental_days"] == 20

        stale = client.patch(
            "/api/v1/admin/settings",
            headers=headers,
            json={"version": 1, "currency": "EUR"},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "stale_version"


def test_concurrent_settings_update_has_one_winner(seeded: SeededSettings) -> None:
    with client_for(seeded.domain_a) as client:
        token = login(client, seeded.owner_email)
        headers = auth(token)

    def update(currency: str) -> int:
        with client_for(seeded.domain_a) as thread_client:
            response = thread_client.patch(
                "/api/v1/admin/settings",
                headers=headers,
                json={"version": 1, "currency": currency},
            )
            return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(update, ("USD", "EUR")))

    assert sorted(statuses) == [200, 409]


def test_settings_permissions_and_validation(seeded: SeededSettings) -> None:
    with client_for(seeded.domain_a) as client:
        owner_token = login(client, seeded.owner_email)
        admin_token = login(client, seeded.admin_email)
        user_token = login(client, seeded.user_email)
        owner_headers = auth(owner_token)

        assert client.get("/api/v1/admin/settings", headers=auth(admin_token)).status_code == 403
        assert client.get("/api/v1/admin/settings", headers=auth(user_token)).status_code == 403
        assert client.get("/api/v1/admin/settings").status_code == 401
        assert (
            client.patch(
                "/api/v1/admin/settings",
                headers=auth(admin_token),
                json={"version": 1, "currency": "USD"},
            ).status_code
            == 403
        )
        assert (
            client.patch(
                "/api/v1/admin/settings",
                headers=auth(user_token),
                json={"version": 1, "currency": "USD"},
            ).status_code
            == 403
        )

        invalid_cases = [
            {"version": 1, "policies": {"booking_horizon_days": 0}},
            {"version": 1, "policies": {"max_rental_days": 91}},
            {"version": 1, "policies": {"lot_photos_max": 21}},
            {"version": 1, "timezone": "Mars/Olympus"},
            {"version": 1, "currency": "usd"},
            {"version": 1, "primary_color": "green"},
            {"version": 1, "logo_url": "ftp://example.com/logo.png"},
            {"version": 1, "unknown": True},
            {"version": 1},
        ]
        for payload in invalid_cases:
            response = client.patch(
                "/api/v1/admin/settings",
                headers=owner_headers,
                json=payload,
            )
            assert response.status_code == 422, payload

        missing_headers = client_for(seeded.domain_a, browser_headers=False)
        with missing_headers:
            blocked = missing_headers.patch(
                "/api/v1/admin/settings",
                headers=owner_headers,
                json={"version": 1, "currency": "USD"},
            )
        assert blocked.status_code == 403
