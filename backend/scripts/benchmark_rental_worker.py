"""Run from backend with DATABASE_URL set: python -m scripts.benchmark_rental_worker."""

import asyncio
import os
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant, User
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.repositories.rental_lifecycle_repository import (
    RentalLifecycleRepository,
)

RENTALS = 10_000
BATCH_SIZE = 500
TIME_LIMIT_SECONDS = 30

SEED_RENTALS = text(
    """
    WITH lots AS (
        INSERT INTO lot (id, tenant_id, category_id, slug, name, rental_unit,
                         allowed_durations, status)
        SELECT gen_random_uuid(), :tenant_id, :category_id, :slug || '-' || i,
               'Benchmark lot ' || i, 'hour', ARRAY[1], 'active'
        FROM generate_series(1, :count) AS i
        RETURNING id
    ), rentals_to_seed AS (
        SELECT id, row_number() OVER (ORDER BY id) <= :half AS expired FROM lots
    ), bookings AS (
        INSERT INTO occupancy (tenant_id, lot_id, kind, period, ref_id, status)
        SELECT :tenant_id, id, 'booking',
               tstzrange(
                   CAST(:now AS timestamptz) - interval '2 hours',
                   CAST(:now AS timestamptz) + CASE WHEN expired THEN interval '-1 hour'
                                                   ELSE interval '1 hour' END,
                   '[)'
               ), gen_random_uuid(), 'active'
        FROM rentals_to_seed
        RETURNING id, lot_id, period, ref_id
    )
    INSERT INTO rental (id, tenant_id, user_id, lot_id, occupancy_id, variant_id,
                        battery_count, start_time, end_time, price_minor, currency,
                        status, cancellation_deadline)
    SELECT ref_id, :tenant_id, :renter_id, lot_id, id, gen_random_uuid(), 0,
           lower(period), upper(period), 100, 'RUB',
           CASE WHEN upper(period) < CAST(:now AS timestamptz) THEN 'active' ELSE 'booked' END,
           lower(period) - interval '24 hours'
    FROM bookings
    """
)


async def seed(
    sessions: async_sessionmaker[AsyncSession], *, tenant_id: UUID, now: datetime
) -> None:
    slug = f"rental-benchmark-{tenant_id.hex[:12]}"
    renter_id, category_id = uuid4(), uuid4()
    async with sessions.begin() as session:
        session.add(Tenant(id=tenant_id, slug=slug, name=slug, domain=f"{slug}.test"))
        await session.flush()
        session.add(CategoryRecord(id=category_id, tenant_id=tenant_id, name=slug, slug=slug))
        session.add_all(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=f"{role}@{slug}.test",
                name=role,
                role=role,
            )
            for user_id, role in ((renter_id, "user"), (uuid4(), "owner"), (uuid4(), "admin"))
        )
        await session.flush()
        await session.execute(
            SEED_RENTALS,
            {
                "tenant_id": tenant_id,
                "renter_id": renter_id,
                "category_id": category_id,
                "slug": slug,
                "count": RENTALS,
                "half": RENTALS // 2,
                "now": now,
            },
        )


async def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required for the benchmark")

    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    tenant_id = uuid4()
    now = datetime.now(UTC)
    try:
        await seed(sessions, tenant_id=tenant_id, now=now)
        activated, overdue = 0, 0
        started = perf_counter()
        # Include every batch commit and one final no-op batch.
        for _ in range(RENTALS // BATCH_SIZE + 1):
            async with sessions.begin() as session:
                configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_worker")
                result = await RentalLifecycleRepository(session).process_batch(
                    now=now, limit=BATCH_SIZE, request_id="rental-worker-benchmark"
                )
            activated += result.activated
            overdue += result.overdue
            if result.activated + result.overdue == 0:
                break
        elapsed = perf_counter() - started

        async with sessions() as session:
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLogRecord)
                .where(AuditLogRecord.tenant_id == tenant_id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(OutboxMessageRecord)
                .where(OutboxMessageRecord.tenant_id == tenant_id)
            )
        print(
            f"{activated:,} activations and {overdue:,} overdue transitions in {elapsed:.2f}s "
            f"(batch size {BATCH_SIZE}, {audit_count} audit rows, {outbox_count} outbox rows)"
        )
        if (activated, overdue, audit_count, outbox_count) != (
            RENTALS // 2,
            RENTALS // 2,
            RENTALS,
            3 * RENTALS // 2,
        ):
            raise SystemExit("Unexpected transition or side-effect counts")
        if elapsed >= TIME_LIMIT_SECONDS:
            raise SystemExit(f"Rental transitions exceeded {TIME_LIMIT_SECONDS}s")
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(AuditLogRecord).where(AuditLogRecord.tenant_id == tenant_id)
            )
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
