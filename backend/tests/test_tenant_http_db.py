from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from tests.factories import TenantSeedFactory, UserSeedFactory

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)


def make_test_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/_test/users")
    async def users(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict[str, list[str]]:
        result = await session.execute(select(User.email))
        return {"emails": list(result.scalars())}

    return router


def seed_tenants() -> tuple[str, str, str, str, tuple[UUID, UUID]]:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    tenant_a_seed = TenantSeedFactory.build(
        name="HTTP Tenant A",
        slug=f"http-a-{suffix}",
        domain=f"http-a-{suffix}.test",
        subdomain=f"http-a-{suffix}",
    )
    tenant_b_seed = TenantSeedFactory.build(
        name="HTTP Tenant B",
        slug=f"http-b-{suffix}",
        domain=f"http-b-{suffix}.test",
        subdomain=f"http-b-{suffix}",
    )
    user_a_seed = UserSeedFactory.build(
        email=f"http-a-{suffix}@example.com",
        name="HTTP User A",
        role="user",
    )
    user_b_seed = UserSeedFactory.build(
        email=f"http-b-{suffix}@example.com",
        name="HTTP User B",
        role="user",
    )

    async def seed() -> tuple[UUID, UUID]:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                tenant_a = Tenant(**tenant_a_seed.__dict__)
                tenant_b = Tenant(**tenant_b_seed.__dict__)
                session.add_all([tenant_a, tenant_b])
                await session.flush()
                session.add_all(
                    [
                        User(tenant_id=tenant_a.id, **user_a_seed.__dict__),
                        User(tenant_id=tenant_b.id, **user_b_seed.__dict__),
                    ]
                )
                await session.commit()
                return tenant_a.id, tenant_b.id
        finally:
            await engine.dispose()

    tenant_ids = asyncio.run(seed())
    return (
        tenant_a_seed.domain,
        tenant_b_seed.domain,
        user_a_seed.email,
        user_b_seed.email,
        tenant_ids,
    )


def cleanup_tenants(tenant_ids: tuple[UUID, UUID]) -> None:
    assert DATABASE_URL is not None

    async def cleanup() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(delete(User).where(User.tenant_id.in_(tenant_ids)))
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(cleanup())


@pytest.fixture
def seeded_http() -> Iterator[tuple[str, str, str, str]]:
    domain_a, domain_b, email_a, email_b, tenant_ids = seed_tenants()
    try:
        yield domain_a, domain_b, email_a, email_b
    finally:
        cleanup_tenants(tenant_ids)


def client_for(host: str) -> TestClient:
    assert DATABASE_URL is not None
    settings = Settings(
        database_url=DATABASE_URL,
        app_env="test",
        platform_domain="platform.test",
        allow_tenant_header=True,
        database_role="keep_rollin_app",
    )
    app = create_app(settings)
    app.include_router(make_test_router())
    return TestClient(app, base_url=f"http://{host}")


def test_http_tenant_resolution_and_rls(seeded_http: tuple[str, str, str, str]) -> None:
    domain_a, domain_b, email_a, email_b = seeded_http

    with client_for(domain_a) as client:
        response_a = client.get("/api/v1/_test/users")

    with client_for(domain_b) as client:
        response_b = client.get("/api/v1/_test/users")

    assert response_a.status_code == 200
    assert response_a.json() == {"emails": [email_a]}
    assert response_b.status_code == 200
    assert response_b.json() == {"emails": [email_b]}


def test_http_unknown_host_returns_problem(seeded_http: tuple[str, str, str, str]) -> None:
    _domain_a, _domain_b, _email_a, _email_b = seeded_http

    with client_for(f"missing-{uuid4().hex}.test") as client:
        response = client.get("/api/v1/_test/users", headers={"X-Request-Id": "http-404"})

    assert response.status_code == 404
    assert response.json()["code"] == "tenant_not_found"
    assert response.json()["trace_id"] == "http-404"


def test_http_platform_subdomain_resolves_tenant(
    seeded_http: tuple[str, str, str, str],
) -> None:
    domain_a, _domain_b, email_a, _email_b = seeded_http
    prefix = domain_a.removesuffix(".test")

    with client_for(f"{prefix}.platform.test") as client:
        response = client.get("/api/v1/_test/users")

    assert response.status_code == 200
    assert response.json() == {"emails": [email_a]}
