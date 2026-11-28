import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant, User
from src.application.services.occupancy import OccupancyService
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.battery_stock_record import BatteryStockRecord
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord, RentalStatus
from src.infrastructure.postgres.repositories.battery_stock_repository import (
    BatteryStockBelowCommittedError,
    BatteryStockConflictError,
    BatteryStockInUseError,
    BatteryStockRepository,
)
from src.infrastructure.postgres.repositories.occupancy_repository import OccupancyRepository
from src.infrastructure.postgres.repositories.rental_repository import RentalRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL is required")

NOW = datetime(2026, 11, 28, tzinfo=UTC)
BATTERY_TYPE = "48v"
PRICE_MINOR = (2**63 - 1) * 2160


@dataclass(frozen=True)
class TenantData:
    id: UUID
    user_id: UUID
    lots: tuple[UUID, UUID, UUID]


@dataclass(frozen=True)
class Fixture:
    sessions: async_sessionmaker[AsyncSession]
    first: TenantData
    second: TenantData


@pytest.fixture
async def fixture() -> AsyncIterator[Fixture]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    tenants = []
    try:
        async with sessions() as session:
            for _ in range(2):
                tenant_id, user_id, category_id = uuid4(), uuid4(), uuid4()
                slug = f"rentals-{tenant_id.hex[:12]}"
                session.add(Tenant(id=tenant_id, slug=slug, name=slug, domain=f"{slug}.test"))
                await session.flush()
                session.add(
                    User(id=user_id, tenant_id=tenant_id, email=f"customer@{slug}.test", name=slug)
                )
                session.add(
                    CategoryRecord(id=category_id, tenant_id=tenant_id, name=slug, slug=slug)
                )
                await session.flush()
                lots = (uuid4(), uuid4(), uuid4())
                session.add_all(
                    [
                        LotRecord(
                            id=lot_id,
                            tenant_id=tenant_id,
                            category_id=category_id,
                            name=f"{slug} {index}",
                            slug=f"{slug}-{index}",
                            rental_unit="hour",
                            battery_type=BATTERY_TYPE,
                            allowed_durations=[1],
                            status="active",
                        )
                        for index, lot_id in enumerate(lots)
                    ]
                )
                tenants.append(TenantData(tenant_id, user_id, lots))
            await session.commit()
        yield Fixture(sessions, tenants[0], tenants[1])
    finally:
        async with sessions() as session:
            await session.execute(
                delete(Tenant).where(Tenant.id.in_([item.id for item in tenants]))
            )
            await session.commit()
        await engine.dispose()


def _period(start_hour: int, end_hour: int) -> TimeRange:
    return TimeRange(NOW + timedelta(hours=start_hour), NOW + timedelta(hours=end_hour))


def _configure(session: AsyncSession, tenant: TenantData) -> None:
    configure_session(session, tenant_id=tenant.id, database_role="keep_rollin_app")


async def _make_rental(
    session: AsyncSession,
    tenant: TenantData,
    lot_id: UUID,
    period: TimeRange,
    *,
    battery_count: int = 1,
    status: RentalStatus = "booked",
) -> RentalRecord:
    rental_id = uuid4()
    occupancy = await OccupancyService(OccupancyRepository(session)).reserve(
        lot_id=lot_id, kind="booking", period=period, ref_id=rental_id
    )
    return await RentalRepository(session).add(
        RentalRecord(
            id=rental_id,
            tenant_id=tenant.id,
            user_id=tenant.user_id,
            lot_id=lot_id,
            occupancy_id=occupancy.id,
            variant_id=uuid4(),
            battery_type=BATTERY_TYPE if battery_count else None,
            battery_count=battery_count,
            status=status,
            start_time=period.start,
            end_time=period.end,
            price_minor=PRICE_MINOR,
            currency="RUB",
            cancellation_deadline=period.start - timedelta(hours=24),
        )
    )


async def test_peak_clips_intervals_and_ignores_overdue_and_past_rentals(fixture: Fixture) -> None:
    tenant = fixture.first
    async with fixture.sessions() as session:
        _configure(session, tenant)
        stock = BatteryStockRepository(session)
        assert await stock.capacity(BATTERY_TYPE, _period(0, 4)) == 0
        await stock.create(BATTERY_TYPE, "48 V", 3)
        with pytest.raises(BatteryStockConflictError):
            await stock.create(BATTERY_TYPE, "Duplicate", 3)
        await _make_rental(session, tenant, tenant.lots[0], _period(-3, -1), battery_count=3)
        await _make_rental(session, tenant, tenant.lots[0], _period(-1, 2), battery_count=2)
        await _make_rental(session, tenant, tenant.lots[1], _period(2, 4), status="active")
        await _make_rental(
            session, tenant, tenant.lots[2], _period(1, 3), status="overdue", battery_count=3
        )

        assert await stock.capacity(BATTERY_TYPE, _period(0, 4), lock=True) == 1
        assert await stock.capacity(BATTERY_TYPE, _period(2, 4)) == 2
        assert await stock.capacity(BATTERY_TYPE, _period(4, 5)) == 3
        assert [peak for _, peak in await stock.list(now=NOW)] == [2]
        with pytest.raises(BatteryStockBelowCommittedError) as below_committed:
            await stock.update_quantity(BATTERY_TYPE, 1, now=NOW)
        assert below_committed.value.peak_committed == 2
        updated, peak = await stock.update_quantity(BATTERY_TYPE, 2, now=NOW)
        assert (updated.quantity, peak) == (2, 2)
        with pytest.raises(BatteryStockInUseError):
            await stock.delete(BATTERY_TYPE)
        await session.commit()


async def test_tenants_and_renter_filters_isolate_rentals_and_stock(fixture: Fixture) -> None:
    first, second = fixture.first, fixture.second
    async with fixture.sessions() as session:
        _configure(session, first)
        await BatteryStockRepository(session).create(BATTERY_TYPE, "48 V", 2)
        rental = await _make_rental(session, first, first.lots[0], _period(1, 2))
        await session.commit()
    async with fixture.sessions() as session:
        _configure(session, second)
        assert list(await session.scalars(select(RentalRecord))) == []
        assert list(await session.scalars(select(BatteryStockRecord))) == []
        assert await RentalRepository(session).lock(rental.id) is None
    async with fixture.sessions() as session:
        _configure(session, first)
        rentals = RentalRepository(session)
        assert await rentals.lock(rental.id, user_id=second.user_id) is None
        assert await rentals.get_details(rental.id, user_id=second.user_id) is None
        assert await rentals.list_page(limit=20, offset=0, period_from=_period(2, 3).start) == (
            [],
            0,
        )
        details = await rentals.get_details(rental.id, user_id=first.user_id)
        assert details is not None
        persisted, lot, user = details
        assert lot.id == first.lots[0]
        assert user.id == first.user_id
        assert persisted.price_minor == PRICE_MINOR
        assert persisted.variant_id == rental.variant_id
        assert persisted.battery_count == 1


@pytest.mark.parametrize("field", ["user_id", "lot_id"])
async def test_rental_foreign_keys_enforce_scope(fixture: Fixture, field: str) -> None:
    first, second = fixture.first, fixture.second
    async with fixture.sessions() as session:
        _configure(session, first)
        rental = await _make_rental(session, first, first.lots[0], _period(1, 2), battery_count=0)
        # The user belongs to another tenant; the occupancy belongs to a different lot.
        setattr(rental, field, second.user_id if field == "user_id" else first.lots[1])
        with pytest.raises(
            IntegrityError,
            match=f"fk_rental_tenant_{'user' if field == 'user_id' else 'lot_occupancy'}",
        ):
            await session.commit()


async def test_stock_lock_serializes_distinct_lots_for_last_battery(fixture: Fixture) -> None:
    first = fixture.first
    period = _period(1, 2)
    async with fixture.sessions() as session:
        _configure(session, first)
        await BatteryStockRepository(session).create(BATTERY_TYPE, "One battery", 1)
        await session.commit()

    barrier = asyncio.Barrier(2)

    async def reserve(lot_id: UUID) -> bool:
        async with fixture.sessions() as session:
            _configure(session, first)
            assert await RentalRepository(session).lock_lot(lot_id) is not None
            await barrier.wait()
            stock = BatteryStockRepository(session)
            if await stock.capacity(BATTERY_TYPE, period, lock=True) < 1:
                return False
            await _make_rental(session, first, lot_id, period)
            await session.commit()
            return True

    results = await asyncio.wait_for(asyncio.gather(*(reserve(lot) for lot in first.lots[:2])), 10)
    assert results.count(True) == 1
