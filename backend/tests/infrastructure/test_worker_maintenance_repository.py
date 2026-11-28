import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant, User
from src.application.services.audit import AuditError
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.idempotency_key_record import IdempotencyKeyRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.models.ticket_record import TicketRecord
from src.infrastructure.postgres.repositories.idempotency_repository import IdempotencyRepository
from src.infrastructure.postgres.repositories.rental_command_repository import (
    RentalCommandRepository,
)
from src.infrastructure.postgres.repositories.ticket_command_repository import (
    TicketCommandRepository,
)
from src.infrastructure.postgres.repositories.worker_maintenance_repository import (
    WorkerMaintenanceRepository,
)
from tests.api.test_rental_reads_api import _create_lot, _create_rental

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")
TICK = datetime(2030, 7, 1, 10, tzinfo=UTC)
HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class Site:
    tenant_id: UUID
    actor: User
    variant: LotVariantRecord

    @property
    def lot_id(self) -> UUID:
        return self.variant.lot_id


@pytest_asyncio.fixture
async def database() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def sites(database: async_sessionmaker[AsyncSession]) -> AsyncIterator[tuple[Site, Site]]:
    pair = []
    async with database.begin() as session:
        for _ in range(2):
            slug = f"worker-maint-{uuid4().hex[:8]}"
            tenant = Tenant(id=uuid4(), name=slug, slug=slug, domain=f"{slug}.test")
            actor = User(id=uuid4(), tenant_id=tenant.id, name=slug, email=f"{slug}@example.test")
            session.add(tenant)
            await session.flush()
            session.add(actor)
            await session.flush()
            pair.append(Site(tenant.id, actor, await _create_lot(session, tenant)))
    try:
        yield pair[0], pair[1]
    finally:
        tenant_ids = [site.tenant_id for site in pair]
        async with database.begin() as session:
            await session.execute(
                delete(AuditLogRecord).where(AuditLogRecord.tenant_id.in_(tenant_ids))
            )
            await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))


@asynccontextmanager
async def worker_session(
    database: async_sessionmaker[AsyncSession], site: Site
) -> AsyncIterator[AsyncSession]:
    async with database() as session:
        configure_session(session, tenant_id=site.tenant_id, database_role="keep_rollin_worker")
        async with session.begin():
            yield session


async def restore(
    database: async_sessionmaker[AsyncSession],
    site: Site,
    now: datetime = TICK,
    trace: str = "tick",
) -> int:
    async with worker_session(database, site) as session:
        return await WorkerMaintenanceRepository(session).return_from_maintenance(now, 1, trace)


def occupancy(
    site: Site,
    start: datetime,
    end: datetime | None,
    *,
    kind: str = "maintenance",
    created_at: datetime | None = None,
    ref_id: UUID | None = None,
) -> OccupancyRecord:
    return OccupancyRecord(
        id=uuid4(),
        tenant_id=site.tenant_id,
        lot_id=site.lot_id,
        kind=kind,
        period=Range(start, end, bounds="[)"),
        ref_id=ref_id or site.lot_id,
        created_by=site.actor.id,
        created_at=created_at or start,
        updated_at=created_at or start,
        status="active",
    )


async def set_maintenance(session: AsyncSession, site: Site) -> LotRecord:
    lot = await session.get_one(LotRecord, site.lot_id)
    lot.status = "maintenance"
    return lot


async def test_staff_ticket_returns_at_boundary_and_keeps_future_booking(
    database: async_sessionmaker[AsyncSession], sites: tuple[Site, Site]
) -> None:
    site, other = sites
    async with database.begin() as session:
        completed = await _create_rental(
            session,
            renter=site.actor,
            variant=site.variant,
            start=TICK - 5 * HOUR,
            status="completed",
            closed_by=site.actor.id,
        )
        booked = await _create_rental(
            session, renter=site.actor, variant=site.variant, start=TICK, status="booked"
        )
        ticket = TicketRecord(
            id=uuid4(),
            tenant_id=site.tenant_id,
            rental_id=completed.id,
            category="other",
            description="The lot needs a timed service.",
        )
        session.add(ticket)
        # The ticket writer uses tenant context even when the fixture uses the admin connection.
        session.info["tenant_id"] = str(site.tenant_id)
        await session.flush()
        await TicketCommandRepository(session).transition(
            ticket.id,
            site.actor.id,
            version=1,
            status="in_progress",
            admin_comment=None,
            maintenance_until=TICK,
        )
        opened = (
            await session.scalars(
                select(OccupancyRecord).where(
                    OccupancyRecord.lot_id == site.lot_id,
                    OccupancyRecord.kind == "maintenance",
                )
            )
        ).one()
        await set_maintenance(session, other)
        foreign_interval = occupancy(other, TICK - HOUR, TICK)
        session.add(foreign_interval)

    assert await restore(database, site, TICK - timedelta(microseconds=1)) == 0
    assert await restore(database, site, trace="maintenance-test-trace") == 1
    assert await restore(database, site) == 0
    async with database() as session:
        lot = await session.get_one(LotRecord, site.lot_id)
        assert (lot.status, lot.version, lot.updated_at) == ("active", 3, TICK)
        history = await session.get_one(OccupancyRecord, opened.id)
        assert (history.status, history.period, history.updated_at) == (
            "released",
            opened.period,
            TICK,
        )
        assert (await session.get_one(OccupancyRecord, booked.occupancy_id)).status == "active"
        assert (await session.get_one(LotRecord, other.lot_id)).status == "maintenance"
        assert (await session.get_one(OccupancyRecord, foreign_interval.id)).status == "active"
        entry = (
            await session.scalars(
                select(AuditLogRecord).where(AuditLogRecord.entity_id == site.lot_id)
            )
        ).one()
        assert (
            entry.action,
            entry.actor_role,
            entry.actor_id,
            entry.request_id,
            entry.created_at,
        ) == ("lot.status_changed", "system", None, "maintenance-test-trace", TICK)
        assert entry.metadata_json == {"old_status": "maintenance", "new_status": "active"}


@pytest.mark.parametrize("case", ["legacy", "external", "manual", "future_maintenance", "archived"])
async def test_ignores_noncanonical_or_superseded_maintenance(
    database: async_sessionmaker[AsyncSession], sites: tuple[Site, Site], case: str
) -> None:
    site, _ = sites
    async with database.begin() as session:
        lot = await set_maintenance(session, site)
        interval = occupancy(site, TICK - HOUR, TICK)
        if case == "legacy":
            interval.created_at += timedelta(minutes=1)
        elif case == "external":
            interval.ref_id = uuid4()
        elif case == "manual":
            session.add(occupancy(site, TICK, None))
        elif case == "future_maintenance":
            session.add(occupancy(site, TICK + HOUR, TICK + 2 * HOUR))
        else:
            lot.status = "archived"
        session.add(interval)

    assert await restore(database, site) == 0
    async with database() as session:
        saved = await session.get_one(LotRecord, site.lot_id)
        assert (saved.status, saved.version) == (lot.status, lot.version)
        history = await session.get_one(OccupancyRecord, interval.id)
        assert (history.status, history.period) == ("active", interval.period)


@pytest.mark.parametrize("blocker", ["block", "maintenance", "active", "overdue"])
async def test_retries_after_current_blocker_is_gone(
    database: async_sessionmaker[AsyncSession], sites: tuple[Site, Site], blocker: str
) -> None:
    site, _ = sites
    rental_id: UUID | None = None
    async with database.begin() as session:
        await set_maintenance(session, site)
        interval = occupancy(site, TICK - 4 * HOUR, TICK - 3 * HOUR)
        session.add(interval)
        if blocker in ("block", "maintenance"):
            block = occupancy(site, TICK - HOUR, TICK + HOUR, kind=blocker, ref_id=uuid4())
            session.add(block)
        else:
            rental = await _create_rental(
                session,
                renter=site.actor,
                variant=site.variant,
                start=TICK - 2 * HOUR,
                status="active" if blocker == "active" else "overdue",
            )
            rental_id = rental.id

    assert await restore(database, site) == 0
    async with database.begin() as session:
        assert (await session.get_one(OccupancyRecord, interval.id)).status == "active"
        if rental_id is not None:
            rental = await session.get_one(RentalRecord, rental_id)
            booking = await session.get_one(OccupancyRecord, rental.occupancy_id)
            booking.status = "released"
            rental.status = "cancelled"
    assert await restore(database, site, TICK + HOUR) == 1


async def test_skips_locked_lot_and_can_retry_without_partial_commit(
    database: async_sessionmaker[AsyncSession], sites: tuple[Site, Site]
) -> None:
    site, _ = sites
    interval = occupancy(site, TICK - HOUR, TICK)
    async with database.begin() as session:
        await set_maintenance(session, site)
        session.add(interval)

    async with database.begin() as session:
        await session.get_one(LotRecord, site.lot_id, with_for_update=True)
        assert await asyncio.wait_for(restore(database, site), timeout=5) == 0

    with pytest.raises(AuditError, match="request id"):
        await restore(database, site, trace="")
    async with database() as session:
        assert (await session.get_one(LotRecord, site.lot_id)).status == "maintenance"
        assert (await session.get_one(OccupancyRecord, interval.id)).status == "active"
    assert await restore(database, site) == 1


async def test_releases_expired_history_after_staff_returns_lot(
    database: async_sessionmaker[AsyncSession], sites: tuple[Site, Site]
) -> None:
    site, _ = sites
    async with database.begin() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        await set_maintenance(session, site)
        interval = occupancy(site, now - 2 * HOUR, now - HOUR)
        session.add(interval)
        rental = await _create_rental(
            session,
            renter=site.actor,
            variant=site.variant,
            start=now - 5 * HOUR,
            status="overdue",
        )

    assert await restore(database, site, now) == 0
    async with database.begin() as session:
        session.info["tenant_id"] = str(site.tenant_id)
        await RentalCommandRepository(session).close(
            rental.id, site.actor.id, comment="The rental was returned.", lot_status="active"
        )
    assert await restore(database, site, now) == 1
    assert await restore(database, site, now) == 0
    async with database() as session:
        saved = await session.get_one(OccupancyRecord, interval.id)
        assert (saved.status, saved.period) == ("released", interval.period)
        lot = await session.get_one(LotRecord, site.lot_id)
        assert lot.status == "active"


async def test_maintenance_batch_restores_only_one_lot_per_call(
    database: async_sessionmaker[AsyncSession], sites: tuple[Site, Site]
) -> None:
    site, _ = sites
    async with database.begin() as session:
        first = await set_maintenance(session, site)
        second = LotRecord(
            id=uuid4(),
            tenant_id=site.tenant_id,
            category_id=first.category_id,
            slug="second-lot",
            name="Second lot",
            rental_unit=first.rental_unit,
            allowed_durations=first.allowed_durations,
            status="maintenance",
        )
        session.add(second)
        await session.flush()
        first_interval = occupancy(site, TICK - HOUR, TICK)
        second_interval = occupancy(site, TICK - HOUR, TICK, ref_id=second.id)
        second_interval.lot_id = second.id
        session.add_all([first_interval, second_interval])

    assert await restore(database, site) == 1
    assert await restore(database, site) == 1
    assert await restore(database, site) == 0


def retry_key(site: Site, expiration: datetime) -> IdempotencyKeyRecord:
    return IdempotencyKeyRecord(
        tenant_id=site.tenant_id,
        user_id=site.actor.id,
        key=uuid4(),
        request_hash="fixture",
        response={"state": "initial"},
        expires_at=expiration,
    )


async def test_key_cleanup_removes_only_oldest_tenant_keys_up_to_batch_size(
    database: async_sessionmaker[AsyncSession], sites: tuple[Site, Site]
) -> None:
    site, other = sites
    oldest, due, live = (retry_key(site, end) for end in (TICK - HOUR, TICK, TICK + HOUR))
    foreign = retry_key(other, TICK - 2 * HOUR)
    async with database.begin() as session:
        session.add_all([oldest, due, live, foreign])

    async with worker_session(database, site) as session:
        repo = WorkerMaintenanceRepository(session)
        assert await repo.delete_expired_idempotency_keys(TICK, 1) == 1
        assert set(await session.scalars(select(IdempotencyKeyRecord.key))) == {due.key, live.key}
        assert await repo.delete_expired_idempotency_keys(TICK, 1) == 1
        assert await repo.delete_expired_idempotency_keys(TICK, 1) == 0
    async with database() as session:
        keys = set(
            await session.scalars(
                select(IdempotencyKeyRecord.key).where(
                    IdempotencyKeyRecord.tenant_id.in_((site.tenant_id, other.tenant_id))
                )
            )
        )
        assert keys == {live.key, foreign.key}


async def test_key_cleanup_rechecks_expiration_after_concurrent_reservation(
    database: async_sessionmaker[AsyncSession], sites: tuple[Site, Site]
) -> None:
    site, _ = sites
    now = datetime.now(UTC)
    expired = retry_key(site, now - HOUR)
    async with database.begin() as session:
        session.add(expired)

    async with database() as reservation, worker_session(database, site) as worker:
        configure_session(reservation, tenant_id=site.tenant_id, database_role="keep_rollin_app")
        reserver = IdempotencyRepository(reservation)
        assert await reserver.reserve(site.actor.id, expired.key, "renewed") is None
        await reserver.save(site.actor.id, expired.key, {"state": "renewed"})
        worker_pid = await worker.scalar(select(func.pg_backend_pid()))
        assert worker_pid is not None
        cleanup = asyncio.create_task(
            WorkerMaintenanceRepository(worker).delete_expired_idempotency_keys(now, 1)
        )
        try:
            async with asyncio.timeout(5), database() as observer:
                # PostgreSQL's lock wait cannot signal a Python asyncio event.
                blocking_pids = select(func.pg_blocking_pids(worker_pid))
                while not await observer.scalar(blocking_pids):  # noqa: ASYNC110
                    await asyncio.sleep(0.01)
            await reservation.commit()
            assert await asyncio.wait_for(cleanup, timeout=5) == 0
        finally:
            if not cleanup.done():
                cleanup.cancel()
                await asyncio.gather(cleanup, return_exceptions=True)

    async with database() as session:
        renewed = await session.get_one(
            IdempotencyKeyRecord, (site.tenant_id, site.actor.id, expired.key)
        )
        assert renewed.expires_at > now
        assert renewed.response == {"state": "renewed"}
