from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant
from src.application.services.occupancy import OccupancyService
from src.domain.exceptions import OccupancyConflictError
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.repositories.occupancy_repository import OccupancyRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)

START = datetime(2026, 1, 1, 10, tzinfo=UTC)
END = datetime(2026, 1, 1, 12, tzinfo=UTC)


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
        name="Occupancy A",
        slug=f"occupancy-a-{suffix}",
        domain=f"occupancy-a-{suffix}.test",
        subdomain=f"occupancy-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Occupancy B",
        slug=f"occupancy-b-{suffix}",
        domain=f"occupancy-b-{suffix}.test",
        subdomain=f"occupancy-b-{suffix}",
    )
    category_a = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        name="E-bikes",
        slug=f"ebikes-{suffix}",
        description=None,
        is_archived=False,
    )
    category_b = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        name="E-bikes B",
        slug=f"ebikes-b-{suffix}",
        description=None,
        is_archived=False,
    )
    lot_a = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"lot-a-{suffix}",
        name="Lot A",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1],
        status="active",
        version=1,
    )
    lot_b = LotRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        category_id=category_b.id,
        slug=f"lot-b-{suffix}",
        name="Lot B",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1],
        status="active",
        version=1,
    )

    async with session_factory() as session:
        session.add_all([tenant_a, tenant_b])
        await session.flush()
        session.add_all([category_a, category_b])
        await session.flush()
        session.add_all([lot_a, lot_b])
        await session.commit()

    try:
        yield tenant_a.id, tenant_b.id, lot_a.id
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant_a.id, tenant_b.id])))
            await session.commit()


async def _reserve(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    lot_id: UUID,
    start: datetime,
    end: datetime,
) -> object | None:
    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_app")
        service = OccupancyService(OccupancyRepository(session))
        try:
            occupancy = await service.reserve(
                lot_id=lot_id,
                kind="booking",
                period=TimeRange(start, end),
            )
            await session.commit()
            return occupancy
        except OccupancyConflictError:
            await session.rollback()
            return None


async def test_overlapping_reservations_race_has_one_winner(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_a, _tenant_b, lot_a = seeded
    results = await asyncio.gather(
        _reserve(session_factory, tenant_a, lot_a, START, END),
        _reserve(session_factory, tenant_a, lot_a, START, END),
    )

    assert sum(result is not None for result in results) == 1


async def test_adjacent_intervals_are_allowed(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_a, _tenant_b, lot_a = seeded
    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        service = OccupancyService(OccupancyRepository(session))
        first = await service.reserve(
            lot_id=lot_a,
            kind="booking",
            period=TimeRange(START, END),
        )
        second = await service.reserve(
            lot_id=lot_a,
            kind="block",
            period=TimeRange(END, datetime(2026, 1, 1, 14, tzinfo=UTC)),
        )
        await session.commit()

    assert first.id != second.id


async def test_release_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_a, _tenant_b, lot_a = seeded
    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        service = OccupancyService(OccupancyRepository(session))
        occupancy = await service.reserve(
            lot_id=lot_a,
            kind="booking",
            period=TimeRange(START, END),
        )
        assert await service.release(occupancy.id) is True
        assert await service.release(occupancy.id) is False
        await session.commit()


async def test_occupancy_is_tenant_scoped(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_a, tenant_b, lot_a = seeded
    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_a, database_role="keep_rollin_app")
        service = OccupancyService(OccupancyRepository(session))
        occupancy = await service.reserve(
            lot_id=lot_a,
            kind="booking",
            period=TimeRange(START, END),
        )
        await session.commit()

    async with session_factory() as session:
        configure_session(session, tenant_id=tenant_b, database_role="keep_rollin_app")
        repository = OccupancyRepository(session)
        assert await repository.list_active(lot_id=lot_a, period=TimeRange(START, END)) == []
        assert await repository.release(occupancy.id) is False
