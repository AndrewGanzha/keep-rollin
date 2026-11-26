from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant, User
from src.domain.entities.offer import OfferNotActiveError, OfferNotEditableError
from src.infrastructure.postgres.models.offer_acceptance_record import OfferAcceptanceRecord
from src.infrastructure.postgres.repositories.offer_repository import OfferRepository

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
async def seeded(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID, UUID]]:
    suffix = uuid4().hex[:10]
    tenant_a = Tenant(
        id=uuid4(),
        name="Offers A",
        slug=f"offers-a-{suffix}",
        domain=f"offers-a-{suffix}.test",
        subdomain=f"offers-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Offers B",
        slug=f"offers-b-{suffix}",
        domain=f"offers-b-{suffix}.test",
        subdomain=f"offers-b-{suffix}",
    )
    user = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"offer-user-{suffix}@example.com",
        name="Offer user",
        role="user",
        password_hash=None,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    async with session_factory() as session:
        session.add_all([tenant_a, tenant_b])
        await session.flush()
        session.add(user)
        await session.commit()
    try:
        yield tenant_a.id, tenant_b.id, user.id
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant_a.id, tenant_b.id])))
            await session.commit()


def _configured(session: AsyncSession, tenant_id: UUID) -> None:
    configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_app")


async def test_offer_publish_acceptance_and_tenant_isolation(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_a, tenant_b, user_id = seeded
    async with session_factory() as session:
        _configured(session, tenant_a)
        repository = OfferRepository(session)
        first = await repository.create_draft(title="Offer 1", body="Terms 1")
        second = await repository.create_draft(title="Offer 2", body="Terms 2")
        assert second.version == 2
        versions, total = await repository.list_versions(limit=20, offset=0)
        assert total == 2
        assert [offer.version for offer in versions] == [2, 1]

        published_first = await repository.publish(first.id)
        assert published_first.status == "active"
        with pytest.raises(OfferNotEditableError):
            await repository.publish(first.id)
        current = await repository.get_current()
        assert current is not None and current.id == first.id

        acceptance = await repository.accept(
            user_id=user_id,
            offer_version_id=first.id,
            ip="127.0.0.1",
        )
        repeat = await repository.accept(
            user_id=user_id,
            offer_version_id=first.id,
            ip="127.0.0.2",
        )
        assert repeat.acceptance.id == acceptance.acceptance.id
        assert await repository.has_accepted_current(user_id=user_id) is True
        count = await session.scalar(select(func.count()).select_from(OfferAcceptanceRecord))
        assert count == 1

        published_second = await repository.publish(second.id)
        assert published_second.status == "active"
        assert await repository.has_accepted_current(user_id=user_id) is False
        with pytest.raises(OfferNotActiveError):
            await repository.accept(
                user_id=user_id,
                offer_version_id=first.id,
                ip=None,
            )
        await repository.accept(
            user_id=user_id,
            offer_version_id=second.id,
            ip=None,
        )
        assert await repository.has_accepted_current(user_id=user_id) is True

        with pytest.raises(OfferNotEditableError):
            await repository.update_draft(second.id, changes={"title": "Active edit"})

    async with session_factory() as session:
        _configured(session, tenant_b)
        repository_b = OfferRepository(session)
        versions_b, total_b = await repository_b.list_versions(limit=20, offset=0)
        assert total_b == 0
        assert versions_b == []
        assert await repository_b.get_current() is None
