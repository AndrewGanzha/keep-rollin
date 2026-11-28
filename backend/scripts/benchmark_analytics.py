"""Benchmark analytics on a migrated disposable PostgreSQL database, from backend."""

import argparse
import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import configure_session, create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.repositories.analytics_repository import (
    AnalyticsRepository,
    _daily_query,
    _totals_query,
)
from src.infrastructure.security.secret_box import SecretBox
from src.infrastructure.security.token_service import JwtTokenService

LOTS = 500
CATEGORIES = 20
RENTALS_PER_LOT = 200
RENTAL_COUNT = LOTS * RENTALS_PER_LOT
START = datetime(2025, 12, 31, 23, tzinfo=UTC)
PERIOD = TimeRange(START, START + timedelta(days=365))
SAMPLES = 20
WARMUP = 5
P95_BUDGET_MS = 300


async def seed(session: AsyncSession, tenant: Tenant, owner_id: UUID, secret: str) -> UUID:
    renter_id, variant_id = uuid4(), uuid4()
    encrypted_mfa = SecretBox.from_settings(secret).encrypt(
        "JBSWY3DPEHPK3PXP", context=f"mfa:{tenant.id}:{owner_id}"
    )
    session.add(tenant)
    await session.flush()
    session.add_all(
        User(
            id=user_id,
            tenant_id=tenant.id,
            email=f"{role}@{tenant.domain}",
            name=f"Benchmark {role}",
            role=role,
            mfa_enabled=role == "owner",
            mfa_secret_enc=encrypted_mfa if role == "owner" else None,
        )
        for role, user_id in (("owner", owner_id), ("user", renter_id))
    )
    categories = [
        CategoryRecord(id=uuid4(), tenant_id=tenant.id, slug=f"category-{n}", name=f"Category {n}")
        for n in range(CATEGORIES)
    ]
    session.add_all(categories)
    await session.flush()
    lots = [
        LotRecord(
            id=uuid4(),
            tenant_id=tenant.id,
            category_id=categories[n % CATEGORIES].id,
            slug=f"lot-{n}",
            name=f"Benchmark lot {n:03}",
            rental_unit="hour",
            allowed_durations=[1],
            status="archived" if n % 20 == 19 else "active",
        )
        for n in range(LOTS)
    ]
    session.add_all(lots)
    await session.flush()
    period_params = {
        "tenant": tenant.id,
        "renter": renter_id,
        "variant": variant_id,
        "lots": [lot.id for lot in lots],
        "start": START,
        "slots": RENTALS_PER_LOT,
    }
    # Keep the fixture small enough to seed quickly without materializing Python records.
    await session.execute(
        text("""
            WITH fixture AS MATERIALIZED (
                SELECT CAST(:tenant AS uuid) AS tenant_id, lot_id, gen_random_uuid() AS rental_id,
                       gen_random_uuid() AS occupancy_id,
                       CAST(:start AS timestamptz) + (40 * slot + ord % 12) * interval '1 hour'
                           AS starts,
                       (ARRAY['completed','completed','completed','active','overdue',
                              'booked','cancelled'])[1 + (slot + ord) % 7] AS status,
                       1000 + 100 * (slot % 11) AS price
                FROM unnest(CAST(:lots AS uuid[])) WITH ORDINALITY AS lot(lot_id, ord)
                CROSS JOIN generate_series(0, :slots - 1) AS slot
            ),
            inserted AS (
                INSERT INTO occupancy (id, tenant_id, lot_id, ref_id, period, status, kind)
                SELECT occupancy_id, tenant_id, lot_id, rental_id,
                       tstzrange(starts, starts + interval '4 hours', '[)'),
                       CASE WHEN status IN ('completed', 'cancelled') THEN 'released'
                            ELSE 'active' END,
                       'booking'
                FROM fixture
                RETURNING id
            )
            INSERT INTO rental (id, tenant_id, user_id, lot_id, occupancy_id, variant_id,
                                battery_count, start_time, end_time, cancellation_deadline,
                                price_minor, currency, status)
            SELECT f.rental_id, f.tenant_id, :renter, f.lot_id, f.occupancy_id, :variant,
                   0, f.starts, f.starts + interval '4 hours', f.starts - interval '1 day',
                   f.price, 'RUB', f.status
            FROM fixture f JOIN inserted i ON i.id = f.occupancy_id
        """),
        period_params,
    )
    return lots[0].id


async def measure(name: str, call: Callable[[], Awaitable[object]]) -> float:
    samples = []
    for index in range(WARMUP + SAMPLES):
        started = perf_counter()
        await call()
        if index >= WARMUP:
            samples.append((perf_counter() - started) * 1000)
    p95 = sorted(samples)[ceil(0.95 * len(samples)) - 1]
    print(f"{name}: median {median(samples):.2f} ms, p95 {p95:.2f} ms", flush=True)
    return p95


async def measure_queries(
    session: AsyncSession, tenant_id: UUID, lot_id: UUID, plan_path: Path | None
) -> None:
    configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_app")
    repository = AnalyticsRepository(session)
    summary = await repository.summary(PERIOD)
    assert summary.rentals_count == RENTAL_COUNT
    assert len(await repository.buckets(PERIOD, "day")) == 365
    assert len(await repository.buckets(PERIOD, "category")) == CATEGORIES
    assert len(await repository.buckets(PERIOD, "lot")) == LOTS
    await measure("SQL summary", lambda: repository.summary(PERIOD))
    await measure("SQL daily", lambda: repository.buckets(PERIOD, "day"))
    await measure("SQL categories", lambda: repository.buckets(PERIOD, "category"))
    await measure("SQL lots", lambda: repository.buckets(PERIOD, "lot"))

    parameters = {"tenant_id": tenant_id, "starts": PERIOD.start, "ends": PERIOD.end}
    plans = []
    for name, query, extra in (
        ("fleet summary", _totals_query(None, filter_lot=False), {}),
        ("day buckets", _daily_query(filter_lot=False), {}),
        ("category buckets", _totals_query("category", filter_lot=False), {}),
        ("lot summary", _totals_query(None, filter_lot=True), {"lot_id": lot_id}),
        (
            "short window summary",
            _totals_query(None, filter_lot=False),
            {"ends": PERIOD.start + timedelta(days=7)},
        ),
    ):
        result = await session.scalars(
            text(f"EXPLAIN (ANALYZE, BUFFERS) {query.text}"), {**parameters, **extra}
        )
        lines = list(result)
        plans.append(f"{name}\n" + "\n".join(lines))
        print(f"EXPLAIN {name}: {lines[-1]}", flush=True)
    if plan_path is not None:
        await asyncio.to_thread(plan_path.write_text, "\n\n".join(plans) + "\n", encoding="utf-8")


async def measure_http(
    database_url: str, tenant: Tenant, owner_id: UUID, lot_id: UUID, category_id: UUID, secret: str
) -> None:
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        app_env="test",
        database_role="keep_rollin_app",
        jwt_secret=secret,
    )
    token = JwtTokenService(secret=settings.jwt_secret).create_access(
        user_id=owner_id, tenant_id=tenant.id, role="owner", token_version=1
    )
    application = create_app(settings)
    logging.getLogger("app.access").setLevel(logging.WARNING)
    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application),
            base_url=f"https://{tenant.domain}",
            headers={"Authorization": f"Bearer {token}"},
        ) as client,
    ):
        params = {"from": PERIOD.start.isoformat(), "to": PERIOD.end.isoformat()}

        async def request(endpoint: str, **query: str) -> object:
            response = await client.get(
                f"/api/v1/admin/analytics/{endpoint}", params=params | query
            )
            response.raise_for_status()
            return response.json()

        samples = [
            await measure("HTTP summary", lambda: request("summary")),
            await measure("HTTP revenue/day", lambda: request("revenue", group_by="day")),
            await measure("HTTP revenue/category", lambda: request("revenue", group_by="category")),
            await measure("HTTP revenue/lot", lambda: request("revenue", group_by="lot")),
            await measure(
                "HTTP revenue/day (one category)",
                lambda: request("revenue", group_by="day", category_id=str(category_id)),
            ),
            await measure("HTTP utilization/day", lambda: request("utilization", group_by="day")),
            await measure("HTTP lot details", lambda: request(f"lots/{lot_id}")),
            await measure(
                "HTTP compare (two full-year periods)",
                lambda: request(
                    "compare",
                    compare_from=(PERIOD.start - timedelta(seconds=1)).isoformat(),
                    compare_to=(PERIOD.end - timedelta(seconds=1)).isoformat(),
                ),
            ),
        ]
    if max(samples) > P95_BUDGET_MS:
        raise SystemExit(f"An analytics endpoint exceeded the {P95_BUDGET_MS} ms p95 budget")


async def main(*, queries_only: bool, plan_path: Path | None) -> None:
    database_url = os.getenv("ANALYTICS_BENCHMARK_DATABASE_URL")
    if not database_url:
        raise SystemExit("Set ANALYTICS_BENCHMARK_DATABASE_URL to a migrated disposable database")
    slug = f"analytics-benchmark-{uuid4().hex[:12]}"
    tenant = Tenant(
        id=uuid4(), slug=slug, name=slug, domain=f"{slug}.test", timezone="Europe/Berlin"
    )
    owner_id = uuid4()
    secret = uuid4().hex + uuid4().hex
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            lot_id = await seed(session, tenant, owner_id, secret)
            category_id = await session.scalar(
                text("SELECT category_id FROM lot WHERE tenant_id = :tenant AND id = :lot"),
                {"tenant": tenant.id, "lot": lot_id},
            )
            assert isinstance(category_id, UUID)
            # Update estimates before the bulk transaction checks deferred foreign keys.
            await session.execute(text('ANALYZE tenant, "user", category, lot, occupancy, rental'))
            version = await session.scalar(text("SHOW server_version"))
        async with engine.connect() as connection:
            # Make the visibility map representative of the mostly historical report rows.
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.exec_driver_sql("VACUUM (ANALYZE) rental, lot, category")
        print(
            f"PostgreSQL {version}; {RENTAL_COUNT} rentals over {LOTS} lots, {CATEGORIES} "
            f"categories and a 365-day window. {SAMPLES} samples after {WARMUP} warm-ups.",
            flush=True,
        )
        async with sessions.begin() as session:
            await measure_queries(session, tenant.id, lot_id, plan_path)
        if not queries_only:
            await measure_http(database_url, tenant, owner_id, lot_id, category_id, secret)
    finally:
        try:
            async with sessions.begin() as session:
                await session.execute(delete(Tenant).where(Tenant.id == tenant.id))
        finally:
            await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries-only", action="store_true")
    parser.add_argument("--plans", type=Path, help="Output file for full EXPLAIN ANALYZE plans")
    args = parser.parse_args()
    asyncio.run(main(queries_only=args.queries_only, plan_path=args.plans))
