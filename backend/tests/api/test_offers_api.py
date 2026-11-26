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
class SeededOffers:
    domain_a: str
    domain_b: str
    tenant_a: UUID
    tenant_b: UUID
    owner_email: str
    admin_email: str
    user_email: str
    owner_b_email: str


def seed_offers() -> SeededOffers:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    hasher = Argon2PasswordHasher()
    tenant_a = Tenant(
        id=uuid4(),
        name="Offers API A",
        slug=f"offers-api-a-{suffix}",
        domain=f"offers-api-a-{suffix}.test",
        subdomain=f"offers-api-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Offers API B",
        slug=f"offers-api-b-{suffix}",
        domain=f"offers-api-b-{suffix}.test",
        subdomain=f"offers-api-b-{suffix}",
    )
    password_hash = hasher.hash(PASSWORD)
    owner = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"owner-{suffix}@example.com",
        name="Owner",
        role="owner",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    admin = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"admin-{suffix}@example.com",
        name="Admin",
        role="admin",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    user = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"user-{suffix}@example.com",
        name="User",
        role="user",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    owner_b = User(
        id=uuid4(),
        tenant_id=tenant_b.id,
        email=f"owner-b-{suffix}@example.com",
        name="Owner B",
        role="owner",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    enable_mfa(owner)
    enable_mfa(admin)
    enable_mfa(owner_b)

    async def seed() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add_all([tenant_a, tenant_b])
                await session.flush()
                session.add_all([owner, admin, user, owner_b])
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return SeededOffers(
        domain_a=tenant_a.domain,
        domain_b=tenant_b.domain,
        tenant_a=tenant_a.id,
        tenant_b=tenant_b.id,
        owner_email=owner.email,
        admin_email=admin.email,
        user_email=user.email,
        owner_b_email=owner_b.email,
    )


def cleanup_offers(tenant_ids: tuple[UUID, UUID]) -> None:
    assert DATABASE_URL is not None

    async def cleanup() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(cleanup())


@pytest.fixture
def seeded() -> Iterator[SeededOffers]:
    value = seed_offers()
    try:
        yield value
    finally:
        cleanup_offers((value.tenant_a, value.tenant_b))


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


def test_offer_publish_acceptance_and_session_flag(seeded: SeededOffers) -> None:
    with client_for(seeded.domain_a) as client:
        public_none = client.get("/api/v1/public/offers/current")
        assert public_none.status_code == 404

        owner_token = login(client, seeded.owner_email)
        user_token = login(client, seeded.user_email)
        owner_headers = auth(owner_token)

        created = client.post(
            "/api/v1/admin/offers",
            headers=owner_headers,
            json={"title": "Offer 1", "body": "Terms 1"},
        )
        assert created.status_code == 201
        first = created.json()
        assert first["version"] == 1
        assert first["status"] == "draft"

        listed = client.get("/api/v1/admin/offers", headers=owner_headers)
        assert listed.status_code == 200
        assert listed.headers["Cache-Control"] == "no-store"
        assert listed.json()["total"] == 1

        edited = client.patch(
            f"/api/v1/admin/offers/{first['id']}",
            headers=owner_headers,
            json={"title": "Offer 1 revised"},
        )
        assert edited.status_code == 200
        assert edited.json()["title"] == "Offer 1 revised"

        published = client.post(
            f"/api/v1/admin/offers/{first['id']}/publish",
            headers=owner_headers,
        )
        assert published.status_code == 200
        assert published.json()["status"] == "active"

        public_current = client.get("/api/v1/public/offers/current")
        assert public_current.status_code == 200
        assert public_current.json()["id"] == first["id"]

        session_before = client.get(
            "/api/v1/auth/session",
            headers=auth(user_token),
        )
        assert session_before.status_code == 200
        assert session_before.json()["offer_accepted"] is False

        accepted = client.post(
            "/api/v1/me/offer-acceptances",
            headers=auth(user_token),
            json={"offer_version_id": first["id"]},
        )
        assert accepted.status_code == 200
        acceptance = accepted.json()
        assert acceptance["version"] == 1

        repeat = client.post(
            "/api/v1/me/offer-acceptances",
            headers=auth(user_token),
            json={"offer_version_id": first["id"]},
        )
        assert repeat.status_code == 200
        assert repeat.json()["id"] == acceptance["id"]

        session_after = client.get("/api/v1/auth/session", headers=auth(user_token))
        assert session_after.json()["offer_accepted"] is True

        acceptances = client.get(
            "/api/v1/me/offer-acceptances",
            headers=auth(user_token),
        )
        assert acceptances.status_code == 200
        assert len(acceptances.json()) == 1

        second = client.post(
            "/api/v1/admin/offers",
            headers=owner_headers,
            json={"title": "Offer 2", "body": "Terms 2"},
        ).json()
        published_second = client.post(
            f"/api/v1/admin/offers/{second['id']}/publish",
            headers=owner_headers,
        )
        assert published_second.status_code == 200
        assert published_second.json()["status"] == "active"

        session_new_offer = client.get("/api/v1/auth/session", headers=auth(user_token))
        assert session_new_offer.json()["offer_accepted"] is False

        old_acceptance = client.post(
            "/api/v1/me/offer-acceptances",
            headers=auth(user_token),
            json={"offer_version_id": first["id"]},
        )
        assert old_acceptance.status_code == 409
        assert old_acceptance.json()["code"] == "offer_not_active"

        active_edit = client.patch(
            f"/api/v1/admin/offers/{second['id']}",
            headers=owner_headers,
            json={"title": "Cannot edit"},
        )
        assert active_edit.status_code == 409
        assert active_edit.json()["code"] == "offer_not_editable"


def test_concurrent_publish_keeps_one_active_offer(seeded: SeededOffers) -> None:
    with client_for(seeded.domain_a) as client:
        owner_token = login(client, seeded.owner_email)
        headers = auth(owner_token)
        first = client.post(
            "/api/v1/admin/offers",
            headers=headers,
            json={"title": "Draft A", "body": "Terms A"},
        ).json()
        second = client.post(
            "/api/v1/admin/offers",
            headers=headers,
            json={"title": "Draft B", "body": "Terms B"},
        ).json()

    def publish(offer_id: str) -> int:
        with client_for(seeded.domain_a) as thread_client:
            response = thread_client.post(
                f"/api/v1/admin/offers/{offer_id}/publish",
                headers=headers,
            )
            return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(publish, (first["id"], second["id"])))

    with client_for(seeded.domain_a) as client:
        listed = client.get("/api/v1/admin/offers", headers=headers)
        public_current = client.get("/api/v1/public/offers/current")

    assert statuses == [200, 200]
    assert listed.status_code == 200
    statuses_by_id = {item["id"]: item["status"] for item in listed.json()["items"]}
    assert list(statuses_by_id.values()).count("active") == 1
    assert public_current.status_code == 200


def test_concurrent_publish_of_same_draft_has_one_winner(seeded: SeededOffers) -> None:
    with client_for(seeded.domain_a) as client:
        owner_token = login(client, seeded.owner_email)
        headers = auth(owner_token)
        draft = client.post(
            "/api/v1/admin/offers",
            headers=headers,
            json={"title": "Draft", "body": "Terms"},
        ).json()

    def publish() -> int:
        with client_for(seeded.domain_a) as thread_client:
            response = thread_client.post(
                f"/api/v1/admin/offers/{draft['id']}/publish",
                headers=headers,
            )
            return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: publish(), range(2)))

    assert sorted(statuses) == [200, 409]


def test_offer_permissions_and_tenant_isolation(seeded: SeededOffers) -> None:
    with client_for(seeded.domain_a) as client:
        owner_token = login(client, seeded.owner_email)
        admin_token = login(client, seeded.admin_email)
        user_token = login(client, seeded.user_email)
        owner_headers = auth(owner_token)

        for token in (admin_token, user_token):
            assert client.get("/api/v1/admin/offers", headers=auth(token)).status_code == 403
            assert (
                client.post(
                    "/api/v1/admin/offers",
                    headers=auth(token),
                    json={"title": "Nope", "body": "Nope"},
                ).status_code
                == 403
            )
        assert client.get("/api/v1/admin/offers").status_code == 401

        created = client.post(
            "/api/v1/admin/offers",
            headers=owner_headers,
            json={"title": "Tenant A", "body": "Terms"},
        ).json()

        with client_for(seeded.domain_a, browser_headers=False) as bare:
            blocked = bare.post(
                "/api/v1/admin/offers",
                headers=owner_headers,
                json={"title": "No CSRF", "body": "Terms"},
            )
        assert blocked.status_code == 403

    with client_for(seeded.domain_b) as client_b:
        owner_b_token = login(client_b, seeded.owner_b_email)
        foreign_publish = client_b.post(
            f"/api/v1/admin/offers/{created['id']}/publish",
            headers=auth(owner_b_token),
        )
        assert foreign_publish.status_code == 404
        assert client_b.get("/api/v1/public/offers/current").status_code == 404
