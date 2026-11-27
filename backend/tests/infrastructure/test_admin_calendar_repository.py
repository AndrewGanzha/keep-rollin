from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant, User
from src.domain.entities.occupancy import BlockNotFoundError, TooManyCalendarLotsError
from src.domain.exceptions import OccupancyConflictError
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.repositories.admin_calendar_repository import (
    AdminCalendarRepository,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
NOW = datetime(2026, 12, 1, 10, tzinfo=UTC)


@dataclass(frozen=True)
class SeededCalendar:
    tenant_a: UUID
    tenant_b: UUID
    user_a: UUID
    category_a: UUID
    lot_a: UUID
    lot_a_second: UUID
    lot_b: UUID
    booking_id: UUID


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
) -> AsyncIterator[SeededCalendar]:
    suffix = uuid4().hex[:10]
    tenant_a = Tenant(
        id=uuid4(),
        name="Calendar A",
        slug=f"calendar-a-{suffix}",
        domain=f"calendar-a-{suffix}.test",
        subdomain=f"calendar-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Calendar B",
        slug=f"calendar-b-{suffix}",
        domain=f"calendar-b-{suffix}.test",
        subdomain=f"calendar-b-{suffix}",
    )
    user_a = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"calendar-user-{suffix}@example.com",
        name="Calendar user",
        role="admin",
        password_hash=None,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    category_a = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        name="Calendar category",
        slug=f"calendar-category-{suffix}",
        description=None,
        is_archived=False,
        version=1,
    )
    category_b = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        name="Calendar category B",
        slug=f"calendar-category-b-{suffix}",
        description=None,
        is_archived=False,
        version=1,
    )
    lot_a = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"calendar-lot-{suffix}",
        name="Calendar lot",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type=None,
        allowed_durations=[1],
        status="active",
        version=1,
    )
    lot_a_second = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"calendar-lot-2-{suffix}",
        name="Calendar lot 2",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type=None,
        allowed_durations=[1],
        status="active",
        version=1,
    )
    lot_b = LotRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        category_id=category_b.id,
        slug=f"calendar-lot-b-{suffix}",
        name="Calendar lot B",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type=None,
        allowed_durations=[1],
        status="active",
        version=1,
    )
    booking = OccupancyRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        kind="booking",
        period=Range(NOW, NOW + timedelta(hours=2), bounds="[)"),
        ref_id=uuid4(),
        status="active",
    )
    active_block = OccupancyRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        kind="block",
        period=Range(NOW + timedelta(hours=3), NOW + timedelta(hours=4), bounds="[)"),
        ref_id=None,
        status="active",
        reason="Active block",
        created_by=user_a.id,
    )
    released_block = OccupancyRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        kind="block",
        period=Range(NOW + timedelta(hours=5), NOW + timedelta(hours=6), bounds="[)"),
        ref_id=None,
        status="released",
        reason="Released block",
        created_by=user_a.id,
    )
    async with session_factory() as session:
        session.add_all([tenant_a, tenant_b])
        await session.flush()
        session.add(user_a)
        session.add_all([category_a, category_b])
        session.add_all([lot_a, lot_a_second, lot_b])
        session.add_all([booking, active_block, released_block])
        await session.commit()
    try:
        yield SeededCalendar(
            tenant_a=tenant_a.id,
            tenant_b=tenant_b.id,
            user_a=user_a.id,
            category_a=category_a.id,
            lot_a=lot_a.id,
            lot_a_second=lot_a_second.id,
            lot_b=lot_b.id,
            booking_id=booking.id,
        )
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant_a.id, tenant_b.id])))
            await session.commit()


def _configured(session: AsyncSession, tenant_id: UUID) -> None:
    configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_app")


async def test_calendar_lists_events_and_filters(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCalendar,
) -> None:
    period = TimeRange(NOW - timedelta(hours=1), NOW + timedelta(hours=7))
    async with session_factory() as session:
        _configured(session, seeded.tenant_a)
        repository = AdminCalendarRepository(session)
        events = await repository.list_events(
            period=period,
            category_id=seeded.category_a,
            lot_id=seeded.lot_a,
            status=None,
        )
        assert {event.kind for event in events} == {"booking", "block"}
        booking = next(event for event in events if event.kind == "booking")
        assert booking.ref_id is not None
        assert booking.period.start == NOW
        assert booking.period.end == NOW + timedelta(hours=2)

        booked = await repository.list_events(
            period=period,
            category_id=None,
            lot_id=None,
            status="booked",
        )
        assert len(booked) == 1
        assert booked[0].kind == "booking"

        active_blocks = await repository.list_events(
            period=period,
            category_id=None,
            lot_id=None,
            status="active",
        )
        assert len(active_blocks) == 1
        assert active_blocks[0].kind == "block"

        released = await repository.list_events(
            period=period,
            category_id=None,
            lot_id=None,
            status="released",
        )
        assert len(released) == 1
        assert released[0].status == "released"

        other_lot = await repository.list_events(
            period=period,
            category_id=seeded.category_a,
            lot_id=seeded.lot_a_second,
            status=None,
        )
        assert other_lot == []


async def test_calendar_lot_scope_and_tenant_isolation(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCalendar,
) -> None:
    period = TimeRange(NOW - timedelta(hours=1), NOW + timedelta(hours=5))
    async with session_factory() as session:
        _configured(session, seeded.tenant_a)
        repository = AdminCalendarRepository(session)
        assert await repository.lot_events(lot_id=seeded.lot_a, period=period) is not None
        assert await repository.lot_events(lot_id=seeded.lot_b, period=period) is None
        with pytest.raises(BlockNotFoundError):
            await repository.create_block(
                lot_id=seeded.lot_b,
                period=TimeRange(NOW + timedelta(hours=6), NOW + timedelta(hours=7)),
                reason="Other tenant",
                created_by=seeded.user_a,
            )

    async with session_factory() as session:
        _configured(session, seeded.tenant_b)
        repository_b = AdminCalendarRepository(session)
        events = await repository_b.list_events(
            period=period,
            category_id=None,
            lot_id=None,
            status=None,
        )
        assert events == []


async def test_legacy_block_without_metadata_is_readable_and_releasable(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCalendar,
) -> None:
    legacy_id = uuid4()
    start = datetime(2026, 12, 20, 12, tzinfo=UTC)
    end = datetime(2026, 12, 20, 13, tzinfo=UTC)
    async with session_factory() as session:
        _configured(session, seeded.tenant_a)
        session.add(
            OccupancyRecord(
                id=legacy_id,
                tenant_id=seeded.tenant_a,
                lot_id=seeded.lot_a_second,
                kind="block",
                period=Range(start, end, bounds="[)"),
                ref_id=None,
                status="active",
            )
        )
        await session.flush()
        repository = AdminCalendarRepository(session)
        events = await repository.list_events(
            period=TimeRange(start - timedelta(hours=1), end + timedelta(hours=1)),
            category_id=None,
            lot_id=seeded.lot_a_second,
            status="active",
        )
        assert len(events) == 1
        assert events[0].reason is None
        assert await repository.release_block(
            lot_id=seeded.lot_a_second,
            block_id=legacy_id,
        )


async def test_calendar_rejects_more_than_200_distinct_lots(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCalendar,
) -> None:
    period = TimeRange(NOW - timedelta(hours=1), NOW + timedelta(hours=5))
    async with session_factory() as session:
        _configured(session, seeded.tenant_a)
        limit_category = CategoryRecord(
            id=uuid4(),
            tenant_id=seeded.tenant_a,
            name="Calendar limit category",
            slug=f"calendar-limit-category-{uuid4().hex[:8]}",
            description=None,
            is_archived=False,
            version=1,
        )
        session.add(limit_category)
        await session.flush()
        lots = []
        occupancies = []
        for index in range(200):
            lot_id = uuid4()
            lots.append(
                LotRecord(
                    id=lot_id,
                    tenant_id=seeded.tenant_a,
                    category_id=limit_category.id,
                    slug=f"calendar-limit-{index}-{uuid4().hex[:8]}",
                    name=f"Limit lot {index}",
                    description=None,
                    photos=[],
                    characteristics={},
                    rental_unit="day",
                    battery_type=None,
                    allowed_durations=[1],
                    status="active",
                    version=1,
                )
            )
            occupancies.append(
                OccupancyRecord(
                    id=uuid4(),
                    tenant_id=seeded.tenant_a,
                    lot_id=lot_id,
                    kind="block",
                    period=Range(NOW + timedelta(hours=3), NOW + timedelta(hours=4), bounds="[)"),
                    ref_id=None,
                    status="active",
                    reason="Bulk block",
                    created_by=seeded.user_a,
                )
            )
        session.add_all(lots)
        await session.flush()
        session.add_all(occupancies)
        await session.flush()

        repository = AdminCalendarRepository(session)
        allowed = await repository.list_events(
            period=period,
            category_id=limit_category.id,
            lot_id=None,
            status=None,
        )
        assert len(allowed) == 200

        extra_lot_id = uuid4()
        session.add(
            LotRecord(
                id=extra_lot_id,
                tenant_id=seeded.tenant_a,
                category_id=limit_category.id,
                slug=f"calendar-limit-extra-{uuid4().hex[:8]}",
                name="Limit extra",
                description=None,
                photos=[],
                characteristics={},
                rental_unit="day",
                battery_type=None,
                allowed_durations=[1],
                status="active",
                version=1,
            )
        )
        await session.flush()
        session.add(
            OccupancyRecord(
                id=uuid4(),
                tenant_id=seeded.tenant_a,
                lot_id=extra_lot_id,
                kind="block",
                period=Range(NOW + timedelta(hours=3), NOW + timedelta(hours=4), bounds="[)"),
                ref_id=None,
                status="active",
                reason="Bulk block",
                created_by=seeded.user_a,
            )
        )
        await session.flush()
        with pytest.raises(TooManyCalendarLotsError):
            await repository.list_events(
                period=period,
                category_id=limit_category.id,
                lot_id=None,
                status=None,
            )
        filtered = await repository.list_events(
            period=period,
            category_id=limit_category.id,
            lot_id=lots[0].id,
            status=None,
        )
        assert len(filtered) == 1


async def test_calendar_block_conflict_release(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCalendar,
) -> None:
    async with session_factory() as session:
        _configured(session, seeded.tenant_a)
        repository = AdminCalendarRepository(session)
        with pytest.raises(OccupancyConflictError):
            await repository.create_block(
                lot_id=seeded.lot_a,
                period=TimeRange(NOW, NOW + timedelta(hours=1)),
                reason="Repair",
                created_by=seeded.user_a,
            )
        await session.rollback()

        _configured(session, seeded.tenant_a)
        block = await repository.create_block(
            lot_id=seeded.lot_a,
            period=TimeRange(
                datetime(2026, 12, 10, 12, tzinfo=UTC),
                datetime(2026, 12, 10, 13, tzinfo=UTC),
            ),
            reason="Repair",
            created_by=seeded.user_a,
        )
        assert block.reason == "Repair"
        assert block.created_by == seeded.user_a
        assert block.period.start == datetime(2026, 12, 9, 21, tzinfo=UTC)
        assert block.period.end == datetime(2026, 12, 10, 21, tzinfo=UTC)
        stored = await session.scalar(select(OccupancyRecord).where(OccupancyRecord.id == block.id))
        assert stored is not None
        assert stored.created_by == seeded.user_a
        assert await repository.release_block(
            lot_id=seeded.lot_a,
            block_id=block.id,
        )
        assert not await repository.release_block(
            lot_id=seeded.lot_a,
            block_id=block.id,
        )
        with pytest.raises(BlockNotFoundError):
            await repository.release_block(lot_id=seeded.lot_a, block_id=uuid4())

        aligned = await repository.create_block(
            lot_id=seeded.lot_a_second,
            period=TimeRange(
                datetime(2026, 12, 14, 21, tzinfo=UTC),
                datetime(2026, 12, 15, 21, tzinfo=UTC),
            ),
            reason="Aligned block",
            created_by=seeded.user_a,
        )
        assert aligned.period.start == datetime(2026, 12, 14, 21, tzinfo=UTC)
        assert aligned.period.end == datetime(2026, 12, 15, 21, tzinfo=UTC)
