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
from src.domain.entities.tenant_profile import (
    SettingsVersionConflictError,
    TenantPolicies,
)
from src.infrastructure.postgres.repositories.admin_settings_repository import (
    AdminSettingsRepository,
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
async def tenant(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[UUID]:
    value = Tenant(
        id=uuid4(),
        name="Settings tenant",
        slug=f"settings-{uuid4().hex[:10]}",
        domain=f"settings-{uuid4().hex[:10]}.test",
        subdomain=f"settings-{uuid4().hex[:10]}",
    )
    async with session_factory() as session:
        session.add(value)
        await session.commit()
    try:
        yield value.id
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == value.id))
            await session.commit()


def _configured(session: AsyncSession, tenant_id: UUID) -> None:
    configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_app")


async def test_settings_defaults_update_and_version(
    session_factory: async_sessionmaker[AsyncSession],
    tenant: UUID,
) -> None:
    async with session_factory() as session:
        _configured(session, tenant)
        repository = AdminSettingsRepository(session)
        state = await repository.get()
        assert state is not None
        assert state.version == 1
        assert state.policies.booking_horizon_days == 60
        assert state.policies.lot_photos_max == 10

        updated = await repository.update(
            version=1,
            changes={"timezone": "Asia/Yekaterinburg", "currency": "USD"},
            policies=TenantPolicies(booking_horizon_days=90, max_rental_days=14),
        )
        assert updated.version == 2
        assert updated.timezone == "Asia/Yekaterinburg"
        assert updated.currency == "USD"
        assert updated.policies.booking_horizon_days == 90
        assert updated.policies.max_rental_days == 14

        with pytest.raises(SettingsVersionConflictError):
            await repository.update(version=1, changes={}, policies=None)


async def test_settings_tenant_isolation(
    session_factory: async_sessionmaker[AsyncSession],
    tenant: UUID,
) -> None:
    other = Tenant(
        id=uuid4(),
        name="Other",
        slug=f"other-settings-{uuid4().hex[:10]}",
        domain=f"other-settings-{uuid4().hex[:10]}.test",
    )
    async with session_factory() as session:
        session.add(other)
        await session.commit()
    try:
        async with session_factory() as session:
            _configured(session, tenant)
            await AdminSettingsRepository(session).update(
                version=1,
                changes={"currency": "USD"},
                policies=None,
            )
        async with session_factory() as session:
            _configured(session, other.id)
            state = await AdminSettingsRepository(session).get()
            assert state is not None
            assert state.currency == "RUB"
            assert state.version == 1
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id == other.id))
            await session.commit()
