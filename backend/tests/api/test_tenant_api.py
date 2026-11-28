from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant
from src.infrastructure.postgres.models.tenant_settings_record import TenantSettingsRecord

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)


@dataclass(frozen=True)
class SeededTenants:
    domain_a: str
    domain_b: str
    tenant_ids: tuple[UUID, UUID]


def seed_tenants() -> SeededTenants:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    tenant_a = Tenant(
        id=uuid4(),
        name="Severny Veter",
        slug=f"severny-{suffix}",
        domain=f"severny-{suffix}.test",
        subdomain=f"severny-{suffix}",
        timezone="Europe/Moscow",
        currency="RUB",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Tenant Without Settings",
        slug=f"plain-{suffix}",
        domain=f"plain-{suffix}.test",
        subdomain=f"plain-{suffix}",
        timezone="Asia/Yekaterinburg",
        currency="USD",
    )

    async def seed() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add_all([tenant_a, tenant_b])
                await session.flush()
                session.add(
                    TenantSettingsRecord(
                        tenant_id=tenant_a.id,
                        logo_url="https://example.com/logo.png",
                        primary_color="#0f766e",
                        policies={
                            "booking_horizon_days": 90,
                            "min_rental_minutes": 30,
                            "max_rental_days": 14,
                            "cancellation_free_hours": 12,
                            "reminder_hours_before": 2,
                            "tickets_per_rental_per_day": 3,
                        },
                        vapid_public_key="vapid-key",
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return SeededTenants(
        domain_a=tenant_a.domain,
        domain_b=tenant_b.domain,
        tenant_ids=(tenant_a.id, tenant_b.id),
    )


def cleanup_tenants(tenant_ids: tuple[UUID, UUID]) -> None:
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
def seeded() -> Iterator[SeededTenants]:
    value = seed_tenants()
    try:
        yield value
    finally:
        cleanup_tenants(value.tenant_ids)


def client_for(domain: str) -> TestClient:
    assert DATABASE_URL is not None
    settings = Settings(
        database_url=DATABASE_URL,
        app_env="test",
        platform_domain="platform.test",
        allow_tenant_header=True,
        database_role="keep_rollin_app",
    )
    return TestClient(create_app(settings), base_url=f"http://{domain}")


def test_public_tenant_returns_branding_and_policies(seeded: SeededTenants) -> None:
    with client_for(seeded.domain_a) as client:
        response = client.get("/api/v1/public/tenant")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Severny Veter"
    assert payload["logo_url"] == "https://example.com/logo.png"
    assert payload["primary_color"] == "#0f766e"
    assert payload["timezone"] == "Europe/Moscow"
    assert payload["currency"] == "RUB"
    assert payload["vapid_public_key"] == "vapid-key"
    assert payload["policies"] == {
        "booking_horizon_days": 90,
        "min_rental_minutes": 30,
        "max_rental_days": 14,
        "cancellation_free_hours": 12,
        "reminder_hours_before": 2,
        "tickets_per_rental_per_day": 3,
        "lot_photos_max": 10,
        "verification_docs_retention_days": 90,
    }
    assert response.headers["cache-control"] == "max-age=300"


def test_public_tenant_uses_defaults_without_settings(seeded: SeededTenants) -> None:
    with client_for(seeded.domain_b) as client:
        response = client.get("/api/v1/public/tenant")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Tenant Without Settings"
    assert payload["currency"] == "USD"
    assert payload["logo_url"] is None
    assert payload["primary_color"] == "#0f766e"
    assert payload["vapid_public_key"] is None
    assert payload["policies"]["booking_horizon_days"] == 60
    assert payload["policies"]["max_rental_days"] == 30


def test_public_tenant_is_tenant_scoped(seeded: SeededTenants) -> None:
    with client_for(seeded.domain_b) as client:
        tenant_b = client.get("/api/v1/public/tenant")
    with client_for(seeded.domain_a) as client:
        tenant_a = client.get("/api/v1/public/tenant")

    assert tenant_a.json()["id"] != tenant_b.json()["id"]
    assert tenant_b.json()["name"] != tenant_a.json()["name"]
