import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import SQLColumnExpression, delete, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant, User
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord, RentalStatus
from src.infrastructure.postgres.repositories.rental_command_repository import (
    RentalCommandRepository,
)
from src.infrastructure.postgres.repositories.rental_lifecycle_repository import (
    RentalLifecycleRepository,
    RentalLifecycleResult,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL is required")
NOW = datetime(2026, 11, 28, 13, tzinfo=UTC)
TRACE_ID = "rental-worker-integration-test"


@dataclass(frozen=True)
class TenantData:
    id: UUID
    renter_id: UUID
    staff_ids: tuple[UUID, UUID]
    lot_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class Fixture:
    sessions: async_sessionmaker[AsyncSession]
    tenants: tuple[TenantData, TenantData]


@pytest.fixture
async def seeded() -> AsyncIterator[Fixture]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    tenant_ids = (uuid4(), uuid4())
    tenants = []
    try:
        async with sessions.begin() as session:
            for tenant_id in tenant_ids:
                slug = f"rental-worker-{tenant_id.hex[:12]}"
                category_id = uuid4()
                renter_id, owner_id, admin_id, former_admin_id = (uuid4() for _ in range(4))
                session.add(Tenant(id=tenant_id, slug=slug, name=slug, domain=f"{slug}.test"))
                await session.flush()
                session.add_all(
                    User(
                        id=user_id,
                        tenant_id=tenant_id,
                        email=f"{user_id}@{slug}.test",
                        name=role,
                        role=role,
                        is_active=active,
                    )
                    for user_id, role, active in (
                        (renter_id, "user", True),
                        (owner_id, "owner", True),
                        (admin_id, "admin", True),
                        (former_admin_id, "admin", False),
                    )
                )
                session.add(
                    CategoryRecord(id=category_id, tenant_id=tenant_id, slug=slug, name=slug)
                )
                await session.flush()
                lot_ids = tuple(uuid4() for _ in range(5))
                session.add_all(
                    LotRecord(
                        id=lot_id,
                        tenant_id=tenant_id,
                        category_id=category_id,
                        slug=f"{slug}-{index}",
                        name=f"Lot {index}",
                        status="active",
                        rental_unit="hour",
                        allowed_durations=[1],
                        updated_at=NOW - timedelta(days=1),
                    )
                    for index, lot_id in enumerate(lot_ids)
                )
                tenants.append(TenantData(tenant_id, renter_id, (owner_id, admin_id), lot_ids))
        yield Fixture(sessions, (tenants[0], tenants[1]))
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(AuditLogRecord).where(AuditLogRecord.tenant_id.in_(tenant_ids))
            )
            await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
        await engine.dispose()


async def _rental(
    session: AsyncSession,
    tenant: TenantData,
    lot_id: UUID,
    *,
    status: RentalStatus,
    start: int,
    end: int,
) -> RentalRecord:
    start_at = NOW + timedelta(hours=start)
    end_at = NOW + timedelta(hours=end)
    rental_id, occupancy_id = uuid4(), uuid4()
    session.add(
        OccupancyRecord(
            id=occupancy_id,
            tenant_id=tenant.id,
            lot_id=lot_id,
            kind="booking",
            status="active" if status not in ("completed", "cancelled") else "released",
            period=Range(start_at, end_at, bounds="[)"),
            ref_id=rental_id,
        )
    )
    record = RentalRecord(
        id=rental_id,
        tenant_id=tenant.id,
        user_id=tenant.renter_id,
        lot_id=lot_id,
        occupancy_id=occupancy_id,
        variant_id=uuid4(),
        battery_count=0,
        status=status,
        start_time=start_at,
        end_time=end_at,
        price_minor=100,
        currency="RUB",
        cancellation_deadline=start_at - timedelta(hours=24),
        updated_at=NOW - timedelta(days=1),
    )
    session.add(record)
    await session.flush()
    return record


async def _batch(
    seeded: Fixture, tenant: TenantData, *, now: datetime = NOW, limit: int = 100
) -> RentalLifecycleResult:
    async with seeded.sessions.begin() as session:
        configure_session(session, tenant_id=tenant.id, database_role="keep_rollin_worker")
        return await RentalLifecycleRepository(session).process_batch(
            now=now, limit=limit, request_id=TRACE_ID
        )


async def test_batch_boundaries_tenant_scope_and_idempotent_side_effects(seeded: Fixture) -> None:
    first, second = seeded.tenants
    async with seeded.sessions.begin() as session:
        overdue = await _rental(session, first, first.lot_ids[0], status="active", start=-2, end=-1)
        exact_end = await _rental(
            session, first, first.lot_ids[1], status="active", start=-1, end=0
        )
        at_start = await _rental(session, first, first.lot_ids[2], status="booked", start=0, end=1)
        future = await _rental(session, first, first.lot_ids[3], status="booked", start=1, end=2)
        other = await _rental(session, second, second.lot_ids[0], status="active", start=-2, end=-1)
        completed = await _rental(
            session, first, first.lot_ids[4], status="completed", start=-2, end=-1
        )

    assert await _batch(seeded, first, limit=1) == RentalLifecycleResult(activated=0, overdue=1)
    assert await _batch(seeded, first, limit=1) == RentalLifecycleResult(activated=1, overdue=0)
    assert await _batch(seeded, first) == RentalLifecycleResult(activated=0, overdue=0)

    async with seeded.sessions() as session:
        rentals = list(
            await session.scalars(
                select(RentalRecord).where(RentalRecord.tenant_id.in_((first.id, second.id)))
            )
        )
        assert {row.id: (row.status, row.version) for row in rentals} == {
            overdue.id: ("overdue", 2),
            exact_end.id: ("active", 1),
            at_start.id: ("active", 2),
            future.id: ("booked", 1),
            other.id: ("active", 1),
            completed.id: ("completed", 1),
        }
        assert {row.id for row in rentals if row.updated_at == NOW} == {overdue.id, at_start.id}
        lot = await session.get(LotRecord, overdue.lot_id)
        assert lot is not None
        assert (lot.status, lot.version, lot.updated_at) == ("overdue", 2, NOW)
        occupancy = await session.get(OccupancyRecord, overdue.occupancy_id)
        assert occupancy is not None
        assert (occupancy.status, occupancy.period) == (
            "active",
            Range(overdue.start_time, overdue.end_time, bounds="[)"),
        )
        audits = list(
            await session.scalars(
                select(AuditLogRecord).where(AuditLogRecord.tenant_id.in_((first.id, second.id)))
            )
        )
        assert {(row.entity_type, row.entity_id, row.action) for row in audits} == {
            ("rental", overdue.id, "rental.overdue"),
            ("lot", overdue.lot_id, "lot.status_changed"),
        }
        assert len(audits) == 2
        assert all(row.tenant_id == first.id and row.actor_id is None for row in audits)
        assert all(row.actor_role == "system" and row.request_id == TRACE_ID for row in audits)
        assert all(row.created_at == NOW for row in audits)
        assert next(row for row in audits if row.entity_type == "lot").metadata_json == {
            "old_status": "active",
            "new_status": "overdue",
        }
        outbox = list(
            await session.scalars(
                select(OutboxMessageRecord).where(
                    OutboxMessageRecord.tenant_id.in_((first.id, second.id))
                )
            )
        )
        assert {(row.event_type, row.user_id) for row in outbox} == {
            ("rental.overdue.user", first.renter_id),
            *(("rental.overdue.admin", user_id) for user_id in first.staff_ids),
        }
        assert len(outbox) == 3
        assert all(row.tenant_id == first.id and row.entity_id == overdue.id for row in outbox)
        assert all(row.status == "pending" and row.available_at == NOW for row in outbox)
        assert all(row.channel is None for row in outbox)


async def test_following_reservation_waits_for_return_even_after_its_end(seeded: Fixture) -> None:
    tenant = seeded.tenants[0]
    lot_id, maintenance_id, *_ = tenant.lot_ids
    async with seeded.sessions.begin() as session:
        earlier = await _rental(session, tenant, lot_id, status="booked", start=-4, end=-3)
        following = await _rental(session, tenant, lot_id, status="booked", start=-3, end=-2)
        maintenance_rental = await _rental(
            session, tenant, maintenance_id, status="active", start=-4, end=-3
        )
        await session.execute(
            update(LotRecord).where(LotRecord.id == maintenance_id).values(status="maintenance")
        )

    assert await _batch(seeded, tenant) == RentalLifecycleResult(activated=1, overdue=1)
    assert await _batch(seeded, tenant) == RentalLifecycleResult(activated=0, overdue=1)
    assert await _batch(seeded, tenant) == RentalLifecycleResult(activated=0, overdue=0)
    async with seeded.sessions.begin() as session:
        configure_session(session, tenant_id=tenant.id, database_role="keep_rollin_app")
        saved = await session.get(RentalRecord, following.id)
        maintenance = await session.get(LotRecord, maintenance_id)
        expired = await session.get(RentalRecord, maintenance_rental.id)
        assert saved is not None and saved.status == "booked"
        assert maintenance is not None and (maintenance.status, maintenance.version) == (
            "maintenance",
            1,
        )
        assert expired is not None and expired.status == "overdue"
        await RentalCommandRepository(session).close(
            earlier.id, tenant.staff_ids[0], comment="Returned", lot_status="active"
        )
    assert await _batch(seeded, tenant) == RentalLifecycleResult(activated=1, overdue=0)
    assert await _batch(seeded, tenant) == RentalLifecycleResult(activated=0, overdue=1)


async def test_cancellation_between_selection_and_update_wins(
    seeded: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = seeded.tenants[0]
    async with seeded.sessions.begin() as session:
        due = await _rental(session, tenant, tenant.lot_ids[0], status="active", start=-2, end=-1)

    original = RentalLifecycleRepository._candidates

    async def cancel_after_selection(
        self: RentalLifecycleRepository,
        *predicates: ColumnElement[bool],
        order_time: SQLColumnExpression[datetime],
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        rows = await original(self, *predicates, order_time=order_time, limit=limit)
        if (due.id, due.lot_id) in rows:
            async with seeded.sessions.begin() as session:
                configure_session(session, tenant_id=tenant.id, database_role="keep_rollin_app")
                await RentalCommandRepository(session).cancel(
                    due.id, tenant.staff_ids[0], own=False, reason="Returned"
                )
        return rows

    monkeypatch.setattr(RentalLifecycleRepository, "_candidates", cancel_after_selection)
    assert await _batch(seeded, tenant) == RentalLifecycleResult(activated=0, overdue=0)
    async with seeded.sessions() as session:
        cancelled = await session.get(RentalRecord, due.id)
        lot = await session.get(LotRecord, due.lot_id)
        assert cancelled is not None and (cancelled.status, cancelled.version) == ("cancelled", 2)
        assert lot is not None and (lot.status, lot.version) == ("active", 1)
        assert (
            await session.scalar(
                select(AuditLogRecord).where(AuditLogRecord.tenant_id == tenant.id)
            )
            is None
        )
        assert (
            await session.scalar(
                select(OutboxMessageRecord).where(OutboxMessageRecord.tenant_id == tenant.id)
            )
            is None
        )


async def test_batch_preserves_lot_overdue_until_all_overdue_rentals_close(seeded: Fixture) -> None:
    tenant = seeded.tenants[0]
    lot_id = tenant.lot_ids[0]
    async with seeded.sessions.begin() as session:
        first = await _rental(session, tenant, lot_id, status="active", start=-4, end=-3)
        second = await _rental(session, tenant, lot_id, status="active", start=-3, end=-2)

    assert await _batch(seeded, tenant) == RentalLifecycleResult(activated=0, overdue=2)
    async with seeded.sessions.begin() as session:
        configure_session(session, tenant_id=tenant.id, database_role="keep_rollin_app")
        lot = await session.get(LotRecord, lot_id)
        assert lot is not None and (lot.status, lot.version) == ("overdue", 2)
        repository = RentalCommandRepository(session)
        await repository.close(
            first.id, tenant.staff_ids[0], comment="Returned", lot_status="active"
        )
        assert (lot.status, lot.version) == ("overdue", 2)
        await repository.close(
            second.id, tenant.staff_ids[0], comment="Returned", lot_status="active"
        )
        assert (lot.status, lot.version) == ("active", 3)


async def test_rollback_and_concurrent_attempts_do_not_duplicate(seeded: Fixture) -> None:
    tenant = seeded.tenants[0]
    async with seeded.sessions.begin() as session:
        due = await _rental(session, tenant, tenant.lot_ids[0], status="active", start=-2, end=-1)

    async with seeded.sessions() as session:
        configure_session(session, tenant_id=tenant.id, database_role="keep_rollin_worker")
        repository = RentalLifecycleRepository(session)
        assert await repository.process_batch(now=NOW, limit=1, request_id=TRACE_ID) == (
            RentalLifecycleResult(activated=0, overdue=1)
        )
        await session.rollback()

    both = await asyncio.wait_for(
        asyncio.gather(_batch(seeded, tenant), _batch(seeded, tenant)), 10
    )
    assert sorted(result.overdue for result in both) == [0, 1]
    async with seeded.sessions() as session:
        rental = await session.get(RentalRecord, due.id)
        assert rental is not None and (rental.status, rental.version) == ("overdue", 2)
        assert (
            len(
                list(
                    await session.scalars(
                        select(AuditLogRecord.id).where(AuditLogRecord.tenant_id == tenant.id)
                    )
                )
            )
            == 2
        )
        assert (
            len(
                list(
                    await session.scalars(
                        select(OutboxMessageRecord.id).where(
                            OutboxMessageRecord.tenant_id == tenant.id
                        )
                    )
                )
            )
            == 3
        )
