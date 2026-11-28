import os
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant, User
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord, RentalStatus
from src.infrastructure.postgres.repositories.analytics_repository import AnalyticsRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL is required")
START = datetime(2026, 3, 29, tzinfo=UTC)
PERIOD = TimeRange(START, START + timedelta(days=2))


@dataclass(frozen=True)
class Seed:
    sessions: async_sessionmaker[AsyncSession]
    tenant_id: UUID
    renter_id: UUID
    category_id: UUID
    empty_category_id: UUID
    first_lot: UUID
    second_lot: UUID
    archived_lot: UUID
    foreign_lot: UUID


async def add_rental(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    lot_id: UUID,
    renter_id: UUID,
    status: RentalStatus,
    price: int,
    starts: int,
    ends: int,
) -> None:
    rental_id, occupancy_id = uuid4(), uuid4()
    start_time, end_time = START + timedelta(hours=starts), START + timedelta(hours=ends)
    session.add(
        OccupancyRecord(
            id=occupancy_id,
            tenant_id=tenant_id,
            lot_id=lot_id,
            kind="booking",
            period=Range(start_time, end_time),
            ref_id=rental_id,
            status="released" if status in ("completed", "cancelled") else "active",
        )
    )
    session.add(
        RentalRecord(
            id=rental_id,
            tenant_id=tenant_id,
            lot_id=lot_id,
            user_id=renter_id,
            occupancy_id=occupancy_id,
            variant_id=uuid4(),
            battery_count=0,
            start_time=start_time,
            end_time=end_time,
            price_minor=price,
            currency="RUB",
            status=status,
            cancellation_deadline=start_time - timedelta(days=1),
        )
    )


@pytest.fixture
async def seeded() -> AsyncIterator[Seed]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    tenant_id, foreign_tenant_id, renter_id, foreign_renter_id = (uuid4() for _ in range(4))
    category_id, empty_category_id, foreign_category_id = (uuid4() for _ in range(3))
    first_lot, second_lot, archived_lot, foreign_lot = (uuid4() for _ in range(4))
    try:
        async with sessions.begin() as session:
            for tid in (tenant_id, foreign_tenant_id):
                slug = f"analytics-{tid.hex[:12]}"
                session.add(
                    Tenant(
                        id=tid,
                        slug=slug,
                        name=slug,
                        domain=f"{slug}.test",
                        timezone="Europe/Berlin",
                    )
                )
            await session.flush()
            for tid, uid in ((tenant_id, renter_id), (foreign_tenant_id, foreign_renter_id)):
                session.add(
                    User(
                        id=uid,
                        tenant_id=tid,
                        email=f"{uid}@example.test",
                        name="Renter",
                        role="user",
                    )
                )
            for tid, cid, name in (
                (tenant_id, category_id, "Used"),
                (tenant_id, empty_category_id, "Empty"),
                (foreign_tenant_id, foreign_category_id, "Foreign"),
            ):
                session.add(CategoryRecord(id=cid, tenant_id=tid, slug=name.lower(), name=name))
            await session.flush()
            for tid, cid, lid, status, name in (
                (tenant_id, category_id, first_lot, "active", "First"),
                (tenant_id, category_id, second_lot, "maintenance", "Second"),
                (tenant_id, category_id, archived_lot, "archived", "Old"),
                (foreign_tenant_id, foreign_category_id, foreign_lot, "active", "Foreign"),
            ):
                session.add(
                    LotRecord(
                        id=lid,
                        tenant_id=tid,
                        category_id=cid,
                        name=name,
                        slug=name.lower(),
                        status=status,
                        rental_unit="hour",
                        allowed_durations=[1],
                    )
                )
            await session.flush()
            cases: list[tuple[UUID, RentalStatus, int, int, int]] = [
                (first_lot, "completed", 999, -4, 0),  # Half-open end at report start.
                (first_lot, "completed", 999, -2, 2),  # A carry-in overlapping the active rental.
                (first_lot, "active", 100, 0, 2),
                (first_lot, "completed", 200, 21, 23),  # Crosses local midnight, not UTC midnight.
                (second_lot, "overdue", 300, 24, 25),
                (second_lot, "booked", 400, 25, 26),
                (second_lot, "cancelled", 500, 26, 27),
                (archived_lot, "completed", 700, 3, 4),
                (first_lot, "active", 999, 48, 49),  # Excluded at report end.
            ]
            for lid, status, price, starts, ends in cases:
                await add_rental(
                    session,
                    tenant_id=tenant_id,
                    lot_id=lid,
                    renter_id=renter_id,
                    status=status,
                    price=price,
                    starts=starts,
                    ends=ends,
                )
            await add_rental(
                session,
                tenant_id=foreign_tenant_id,
                lot_id=foreign_lot,
                renter_id=foreign_renter_id,
                status="active",
                price=9_999,
                starts=1,
                ends=4,
            )
        yield Seed(
            sessions,
            tenant_id,
            renter_id,
            category_id,
            empty_category_id,
            first_lot,
            second_lot,
            archived_lot,
            foreign_lot,
        )
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(Tenant).where(Tenant.id.in_((tenant_id, foreign_tenant_id)))
            )
        await engine.dispose()


async def test_financial_totals_and_clipped_unique_utilization(seeded: Seed) -> None:
    async with seeded.sessions.begin() as session:
        configure_session(session, tenant_id=seeded.tenant_id, database_role="keep_rollin_app")
        repository = AnalyticsRepository(session)
        summary = await repository.summary(PERIOD)
        assert summary.model_dump(exclude={"period_from", "period_to"}) == {
            "revenue_minor": 1300,
            "rentals_count": 6,
            "cancelled_count": 1,
            "overdue_count": 1,
            "avg_rental_minor": 260,
            "utilization_pct": 5.2,
        }
        assert (await repository.summary(PERIOD, lot_id=seeded.first_lot)).utilization_pct == 8.3
        assert (await repository.summary(PERIOD, lot_id=seeded.archived_lot)).utilization_pct == 0
        assert (await repository.summary(PERIOD, lot_id=seeded.foreign_lot)).rentals_count == 0
        categories = {row.key: row for row in await repository.buckets(PERIOD, "category")}
        assert set(categories) == {str(seeded.category_id), str(seeded.empty_category_id)}
        assert categories[str(seeded.category_id)].utilization_pct == 5.2
        assert categories[str(seeded.empty_category_id)].rentals_count == 0
        lots = {row.key: row for row in await repository.buckets(PERIOD, "lot")}
        assert set(lots) == {
            str(seeded.first_lot),
            str(seeded.second_lot),
            str(seeded.archived_lot),
        }
        assert lots[str(seeded.archived_lot)].revenue_minor == 700
        assert lots[str(seeded.second_lot)].utilization_pct == 2.1

        assert await repository.summary(PERIOD, category_id=seeded.category_id) == summary
        assert (
            await repository.summary(PERIOD, category_id=seeded.empty_category_id)
        ).rentals_count == 0
        assert await repository.buckets(PERIOD, "lot", category_id=seeded.empty_category_id) == []
        scoped_days = await repository.buckets(PERIOD, "day", category_id=seeded.empty_category_id)
        assert len(scoped_days) == 3
        assert all(not day.rentals_count and not day.utilization_pct for day in scoped_days)


async def test_local_days_clip_dst_and_zero_fill(seeded: Seed) -> None:
    async with seeded.sessions.begin() as session:
        configure_session(session, tenant_id=seeded.tenant_id, database_role="keep_rollin_app")
        repository = AnalyticsRepository(session)
        days = await repository.buckets(PERIOD, "day")
        assert [(d.key, d.rentals_count, d.revenue_minor, d.utilization_pct) for d in days] == [
            ("2026-03-29", 3, 1000, 6.8),  # Only 22 hours from 01:00 local on the DST day.
            ("2026-03-30", 3, 300, 4.2),
            ("2026-03-31", 0, 0, 0.0),
        ]
        after = TimeRange(START + timedelta(days=10), START + timedelta(days=11))
        assert (await repository.summary(after)).rentals_count == 0
        days = await repository.buckets(after, "day")
        assert [d.key for d in days] == ["2026-04-08", "2026-04-09"]
        assert all(d.revenue_minor == 0 and d.utilization_pct == 0 for d in days)


async def test_scoped_detail_paging_and_exports(seeded: Seed) -> None:
    async with seeded.sessions.begin() as session:
        configure_session(session, tenant_id=seeded.tenant_id, database_role="keep_rollin_app")
        repository = AnalyticsRepository(session)
        lot = await repository.lot(seeded.second_lot)
        assert lot is not None and lot.name == "Second"
        assert await repository.lot(seeded.foreign_lot) is None
        assert await repository.rentals(PERIOD, seeded.foreign_lot, limit=10, offset=0) == []
        page = await repository.rentals(PERIOD, seeded.second_lot, limit=1, offset=1)
        assert len(page) == 1 and page[0].status == "booked" and page[0].user.id == seeded.renter_id
        exported = [row async for row in repository.iter_export(PERIOD)]
        assert [row.price_minor for row in exported] == [100, 700, 200, 300, 400, 500]
        assert all(
            row.category_name == "Used" and "user" not in row.model_dump() for row in exported
        )
        async with aclosing(repository.iter_export(PERIOD)) as rows:
            assert (await anext(rows)).id == exported[0].id
        assert await repository.summary(PERIOD) is not None


async def test_day_includes_the_first_fold_of_repeated_midnight(seeded: Seed) -> None:
    start = datetime(2026, 11, 1, 4, tzinfo=UTC)  # First 00:00 in Havana.
    period = TimeRange(start, start + timedelta(hours=1))
    starts = (start - START) // timedelta(hours=1)
    async with seeded.sessions.begin() as session:
        await session.execute(
            update(Tenant).where(Tenant.id == seeded.tenant_id).values(timezone="America/Havana")
        )
        await add_rental(
            session,
            tenant_id=seeded.tenant_id,
            lot_id=seeded.first_lot,
            renter_id=seeded.renter_id,
            status="completed",
            price=100,
            starts=starts,
            ends=starts + 1,
        )
    async with seeded.sessions.begin() as session:
        configure_session(session, tenant_id=seeded.tenant_id, database_role="keep_rollin_app")
        buckets = await AnalyticsRepository(session).buckets(period, "day")
        assert [(b.key, b.revenue_minor, b.utilization_pct) for b in buckets] == [
            ("2026-11-01", 100, 50.0)
        ]
