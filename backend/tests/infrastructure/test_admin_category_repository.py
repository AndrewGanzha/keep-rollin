from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant
from src.domain.entities.category import (
    CategoryNotFoundError,
    CategorySlugTakenError,
    CategoryVersionConflictError,
)
from src.infrastructure.postgres.repositories.admin_category_repository import (
    AdminCategoryRepository,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest_asyncio.fixture
async def tenants(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID]]:
    suffix = uuid4().hex[:10]
    tenant_a = Tenant(
        id=uuid4(),
        name="Admin A",
        slug=f"admin-a-{suffix}",
        domain=f"admin-a-{suffix}.test",
        subdomain=f"admin-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Admin B",
        slug=f"admin-b-{suffix}",
        domain=f"admin-b-{suffix}.test",
        subdomain=f"admin-b-{suffix}",
    )
    async with session_factory() as session:
        session.add_all([tenant_a, tenant_b])
        await session.commit()
    try:
        yield tenant_a.id, tenant_b.id
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant_a.id, tenant_b.id])))
            await session.commit()


def _configured(session: AsyncSession, tenant_id: UUID) -> None:
    configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_app")


async def test_admin_category_crud_and_optimistic_version(
    session_factory: async_sessionmaker[AsyncSession],
    tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, _tenant_b = tenants
    async with session_factory() as session:
        _configured(session, tenant_a)
        repository = AdminCategoryRepository(session)
        created = await repository.create(
            name="E-bikes",
            slug="ebikes",
            description="Electric bikes",
        )
        assert created.version == 1

        listed, total = await repository.list(include_archived=False, limit=20, offset=0)
        assert total == 1
        assert listed[0].id == created.id

        updated = await repository.update(
            created.id,
            version=1,
            changes={"name": "Road bikes"},
        )
        assert updated.name.value == "Road bikes"
        assert updated.version == 2

        with pytest.raises(CategoryVersionConflictError):
            await repository.update(created.id, version=1, changes={"name": "Stale"})
        await session.rollback()


async def test_admin_category_archive_and_include_archived(
    session_factory: async_sessionmaker[AsyncSession],
    tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, _tenant_b = tenants
    async with session_factory() as session:
        _configured(session, tenant_a)
        repository = AdminCategoryRepository(session)
        created = await repository.create(name="E-bikes", slug="ebikes", description=None)
        await repository.update(created.id, version=1, changes={"is_archived": True})

        visible, visible_total = await repository.list(
            include_archived=False,
            limit=20,
            offset=0,
        )
        all_categories, all_total = await repository.list(
            include_archived=True,
            limit=20,
            offset=0,
        )

        assert visible == []
        assert visible_total == 0
        assert all_total == 1
        assert all_categories[0].is_archived is True


async def test_admin_category_duplicate_slug(
    session_factory: async_sessionmaker[AsyncSession],
    tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, _tenant_b = tenants
    async with session_factory() as session:
        _configured(session, tenant_a)
        repository = AdminCategoryRepository(session)
        await repository.create(name="E-bikes", slug="ebikes", description=None)
        second = await repository.create(name="Cargo", slug="cargo", description=None)
        second_id = second.id
        await session.commit()

        with pytest.raises(CategorySlugTakenError):
            await repository.create(name="Duplicate", slug="ebikes", description=None)
        await session.rollback()

        _configured(session, tenant_a)
        with pytest.raises(CategorySlugTakenError):
            await repository.update(second_id, version=1, changes={"slug": "ebikes"})
        await session.rollback()


async def test_admin_category_tenant_isolation(
    session_factory: async_sessionmaker[AsyncSession],
    tenants: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = tenants
    async with session_factory() as session:
        _configured(session, tenant_a)
        created = await AdminCategoryRepository(session).create(
            name="E-bikes",
            slug="ebikes",
            description=None,
        )
        await session.commit()

    async with session_factory() as session:
        _configured(session, tenant_b)
        repository = AdminCategoryRepository(session)
        listed, total = await repository.list(include_archived=True, limit=20, offset=0)
        assert total == 0
        assert listed == []
        with pytest.raises(CategoryNotFoundError):
            await repository.update(created.id, version=1, changes={"name": "Hijack"})
