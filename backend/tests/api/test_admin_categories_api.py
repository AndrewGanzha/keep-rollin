from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.security.password_hasher import Argon2PasswordHasher

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
JWT_SECRET = "test-secret-keep-rollin-0123456789abcdef"
PASSWORD = "Bike-Rider-2026!"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SeededAdminCategories:
    domain_a: str
    domain_b: str
    tenant_a: UUID
    tenant_b: UUID
    owner_a_email: str
    admin_a_email: str
    user_a_email: str
    owner_b_email: str
    active_category_id: UUID
    archived_category_id: UUID
    active_category_slug: str
    archived_category_slug: str
    category_b_id: UUID
    lot_slug: str


def seed_admin_categories() -> SeededAdminCategories:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    hasher = Argon2PasswordHasher()
    tenant_a = Tenant(
        id=uuid4(),
        name="Admin API A",
        slug=f"admin-api-a-{suffix}",
        domain=f"admin-api-a-{suffix}.test",
        subdomain=f"admin-api-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Admin API B",
        slug=f"admin-api-b-{suffix}",
        domain=f"admin-api-b-{suffix}.test",
        subdomain=f"admin-api-b-{suffix}",
    )
    owner_a_email = f"owner-a-{suffix}@example.com"
    admin_a_email = f"admin-a-{suffix}@example.com"
    user_a_email = f"user-a-{suffix}@example.com"
    owner_b_email = f"owner-b-{suffix}@example.com"
    password_hash = hasher.hash(PASSWORD)
    owner_a = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=owner_a_email,
        name="Owner A",
        role="owner",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    admin_a = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=admin_a_email,
        name="Admin A",
        role="admin",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    user_a = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=user_a_email,
        name="User A",
        role="user",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    owner_b = User(
        id=uuid4(),
        tenant_id=tenant_b.id,
        email=owner_b_email,
        name="Owner B",
        role="owner",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    active_category = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        name="E-bikes",
        slug=f"active-{suffix}",
        description="Active category",
        is_archived=False,
        version=1,
    )
    archived_category = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        name="Old bikes",
        slug=f"archived-{suffix}",
        description=None,
        is_archived=True,
        version=1,
    )
    category_b = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        name="Tenant B bikes",
        slug=f"tenant-b-{suffix}",
        description=None,
        is_archived=False,
        version=1,
    )
    lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=active_category.id,
        slug=f"lot-{suffix}",
        name="Visible lot",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    variant = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot.id,
        battery_count=1,
        is_active=True,
    )
    tier = LotPriceTierRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        variant_id=variant.id,
        min_units=1,
        price_per_unit_minor=1000,
    )

    async def seed() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add_all([tenant_a, tenant_b])
                await session.flush()
                session.add_all([owner_a, admin_a, user_a, owner_b])
                session.add_all([active_category, archived_category, category_b])
                session.add(lot)
                await session.flush()
                session.add_all([variant, tier])
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return SeededAdminCategories(
        domain_a=tenant_a.domain,
        domain_b=tenant_b.domain,
        tenant_a=tenant_a.id,
        tenant_b=tenant_b.id,
        owner_a_email=owner_a_email,
        admin_a_email=admin_a_email,
        user_a_email=user_a_email,
        owner_b_email=owner_b_email,
        active_category_id=active_category.id,
        archived_category_id=archived_category.id,
        active_category_slug=active_category.slug,
        archived_category_slug=archived_category.slug,
        category_b_id=category_b.id,
        lot_slug=lot.slug,
    )


def cleanup_admin_categories(tenant_ids: tuple[UUID, UUID]) -> None:
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
def seeded() -> Iterator[SeededAdminCategories]:
    value = seed_admin_categories()
    try:
        yield value
    finally:
        cleanup_admin_categories((value.tenant_a, value.tenant_b))


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
    return TestClient(
        create_app(settings),
        base_url=f"https://{domain}",
        headers=headers,
    )


def login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_owner_category_crud_and_versions(seeded: SeededAdminCategories) -> None:
    with client_for(seeded.domain_a) as client:
        token = login(client, seeded.owner_a_email)
        headers = auth(token)

        listed = client.get("/api/v1/admin/categories", headers=headers)
        assert listed.status_code == 200
        assert listed.headers["Cache-Control"] == "no-store"
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["id"] == str(seeded.active_category_id)

        created = client.post(
            "/api/v1/admin/categories",
            headers=headers,
            json={
                "name": "  Cargo bikes  ",
                "slug": f"cargo-{uuid4().hex[:8]}",
                "description": "Cargo",
            },
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["name"] == "Cargo bikes"
        assert payload["version"] == 1
        category_id = payload["id"]

        duplicate = client.post(
            "/api/v1/admin/categories",
            headers=headers,
            json={
                "name": "Duplicate",
                "slug": payload["slug"],
                "description": None,
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "slug_taken"

        updated = client.patch(
            f"/api/v1/admin/categories/{category_id}",
            headers=headers,
            json={"name": "Cargo two", "version": 1},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Cargo two"
        assert updated.json()["version"] == 2

        stale = client.patch(
            f"/api/v1/admin/categories/{category_id}",
            headers=headers,
            json={"name": "Stale", "version": 1},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "stale_version"

        missing_version = client.patch(
            f"/api/v1/admin/categories/{category_id}",
            headers=headers,
            json={"name": "No version"},
        )
        assert missing_version.status_code == 422
        assert "version" in missing_version.json()["fields"]

        empty_patch = client.patch(
            f"/api/v1/admin/categories/{category_id}",
            headers=headers,
            json={"version": 2},
        )
        assert empty_patch.status_code == 422
        assert "body" in empty_patch.json()["fields"]

        with_archived = client.get(
            "/api/v1/admin/categories?include_archived=true",
            headers=headers,
        )
        assert with_archived.status_code == 200
        archived_ids = {item["id"] for item in with_archived.json()["items"]}
        assert str(seeded.archived_category_id) in archived_ids

        page = client.get(
            "/api/v1/admin/categories?limit=1&offset=0",
            headers=headers,
        )
        assert page.status_code == 200
        assert page.json()["limit"] == 1
        assert page.json()["offset"] == 0
        assert len(page.json()["items"]) == 1


def test_admin_and_user_cannot_manage_categories(seeded: SeededAdminCategories) -> None:
    with client_for(seeded.domain_a) as client:
        admin_token = login(client, seeded.admin_a_email)
        user_token = login(client, seeded.user_a_email)
        admin_list = client.get("/api/v1/admin/categories", headers=auth(admin_token))
        admin_create = client.post(
            "/api/v1/admin/categories",
            headers=auth(admin_token),
            json={"name": "Nope", "slug": "nope", "description": None},
        )
        user_list = client.get("/api/v1/admin/categories", headers=auth(user_token))
        anonymous = client.get("/api/v1/admin/categories")

    assert admin_list.status_code == 403
    assert admin_create.status_code == 403
    assert user_list.status_code == 403
    assert anonymous.status_code == 401


def test_archive_hides_category_and_lots_from_public(seeded: SeededAdminCategories) -> None:
    with client_for(seeded.domain_a) as client:
        before_categories = client.get("/api/v1/public/categories")
        before_lots = client.get("/api/v1/public/lots")
        assert seeded.active_category_slug in {item["slug"] for item in before_categories.json()}
        assert seeded.lot_slug in {item["slug"] for item in before_lots.json()["items"]}

        token = login(client, seeded.owner_a_email)
        archived = client.patch(
            f"/api/v1/admin/categories/{seeded.active_category_id}",
            headers=auth(token),
            json={"is_archived": True, "version": 1},
        )
        assert archived.status_code == 200
        assert archived.json()["version"] == 2

        after_categories = client.get("/api/v1/public/categories")
        after_lots = client.get("/api/v1/public/lots")

    assert seeded.active_category_slug not in {item["slug"] for item in after_categories.json()}
    assert seeded.lot_slug not in {item["slug"] for item in after_lots.json()["items"]}


def test_tenant_isolation_and_csrf(seeded: SeededAdminCategories) -> None:
    with client_for(seeded.domain_a) as client:
        owner_a_token = login(client, seeded.owner_a_email)
    with client_for(seeded.domain_b) as client_b:
        owner_b_token = login(client_b, seeded.owner_b_email)
        foreign_patch = client_b.patch(
            f"/api/v1/admin/categories/{seeded.active_category_id}",
            headers=auth(owner_b_token),
            json={"name": "Hijack", "version": 1},
        )
        own_list = client_b.get("/api/v1/admin/categories", headers=auth(owner_b_token))

    assert foreign_patch.status_code == 404
    assert own_list.status_code == 200
    assert {item["id"] for item in own_list.json()["items"]} == {str(seeded.category_b_id)}

    with client_for(seeded.domain_a, browser_headers=False) as bare:
        missing_headers = bare.post(
            "/api/v1/admin/categories",
            headers=auth(owner_a_token),
            json={"name": "No CSRF", "slug": f"no-csrf-{uuid4().hex[:8]}", "description": None},
        )
    assert missing_headers.status_code == 403


def test_create_category_validates_input(seeded: SeededAdminCategories) -> None:
    with client_for(seeded.domain_a) as client:
        token = login(client, seeded.owner_a_email)
        headers = auth(token)
        invalid_slug = client.post(
            "/api/v1/admin/categories",
            headers=headers,
            json={"name": "Bad", "slug": "Bad Slug", "description": None},
        )
        blank_name = client.post(
            "/api/v1/admin/categories",
            headers=headers,
            json={"name": "   ", "slug": f"blank-{uuid4().hex[:8]}", "description": None},
        )
        nul_name = client.post(
            "/api/v1/admin/categories",
            headers=headers,
            json={"name": "Bad\x00", "slug": f"nul-{uuid4().hex[:8]}", "description": None},
        )

    for response, field in (
        (invalid_slug, "slug"),
        (blank_name, "name"),
        (nul_name, "name"),
    ):
        assert response.status_code == 422
        assert field in response.json()["fields"]
