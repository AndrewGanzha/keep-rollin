"""Run from backend against a migrated disposable PostgreSQL database."""

import asyncio
import logging
import os
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from math import ceil
from statistics import median
from time import perf_counter
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.infrastructure.postgres.models.battery_stock_record import BatteryStockRecord
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.security.secret_box import SecretBox
from src.infrastructure.security.token_service import JwtTokenService

SCHEDULE_DAYS = 30
LOTS = 50
OCCUPIED_LOTS = 40
BOOKINGS_PER_LOT = 5
BLOCKS = 5
VARIANTS = 20
QUOTE_OCCUPANCY = 200
BATTERY_TYPE = "48v"
FREE_BATTERIES = 10
QUOTE_SLUG = "quote-lot"
WARMUP = 5
SAMPLES = 50
SCHEDULE_LIMIT_MS = 200
QUOTE_P95_LIMIT_MS = 150


def add_booking(session: AsyncSession, lot: LotRecord, renter_id: UUID, start: datetime) -> None:
    end = start + timedelta(hours=1)
    occupancy_id, rental_id = uuid4(), uuid4()
    variant = lot.variants[0]
    session.add(
        OccupancyRecord(
            id=occupancy_id,
            tenant_id=lot.tenant_id,
            lot_id=lot.id,
            kind="booking",
            period=Range(start, end, bounds="[)"),
            ref_id=rental_id,
            status="active",
        )
    )
    session.add(
        RentalRecord(
            id=rental_id,
            tenant_id=lot.tenant_id,
            user_id=renter_id,
            lot_id=lot.id,
            variant_id=variant.id,
            occupancy_id=occupancy_id,
            battery_type=lot.battery_type if variant.battery_count else None,
            battery_count=variant.battery_count,
            start_time=start,
            end_time=end,
            cancellation_deadline=start - timedelta(days=1),
            price_minor=variant.price_tiers[0].price_per_unit_minor,
            currency="RUB",
            status="booked",
        )
    )


async def seed(
    session: AsyncSession, tenant: Tenant, owner_id: UUID, start: datetime, secret: str
) -> tuple[LotRecord, UUID]:
    category_id, renter_id = uuid4(), uuid4()
    session.add(tenant)
    await session.flush()
    session.add_all(
        [
            User(
                id=owner_id,
                tenant_id=tenant.id,
                email=f"owner@{tenant.domain}",
                name="Benchmark owner",
                role="owner",
                mfa_enabled=True,
                mfa_secret_enc=SecretBox.from_settings(secret).encrypt(
                    "JBSWY3DPEHPK3PXP", context=f"mfa:{tenant.id}:{owner_id}"
                ),
            ),
            User(
                id=renter_id,
                tenant_id=tenant.id,
                email=f"renter@{tenant.domain}",
                name="Benchmark renter",
                role="user",
            ),
            CategoryRecord(id=category_id, tenant_id=tenant.id, name="Benchmark", slug="benchmark"),
            BatteryStockRecord(
                tenant_id=tenant.id,
                battery_type=BATTERY_TYPE,
                name="48 V",
                quantity=OCCUPIED_LOTS + FREE_BATTERIES,
            ),
        ]
    )
    await session.flush()

    lots = []
    for index in range(LOTS):
        is_quote_lot = index == 0
        lot = LotRecord(
            id=uuid4(),
            tenant_id=tenant.id,
            category_id=category_id,
            slug=QUOTE_SLUG if is_quote_lot else f"benchmark-lot-{index}",
            name=f"Benchmark lot {index:02}",
            rental_unit="hour",
            allowed_durations=[1],
            status="active",
            battery_type=BATTERY_TYPE,
        )
        lot.variants = [
            LotVariantRecord(
                id=uuid4(),
                tenant_id=tenant.id,
                battery_count=count,
                price_tiers=[
                    LotPriceTierRecord(
                        id=uuid4(),
                        tenant_id=tenant.id,
                        min_units=1,
                        price_per_unit_minor=2000 + 100 * count,
                    )
                ],
            )
            for count in (range(VARIANTS) if is_quote_lot else (1,))
        ]
        lots.append(lot)
    session.add_all(lots)
    await session.flush()

    # Keep the quoted lot free so the quote reads all overlapping bookings for battery capacity.
    for lot in lots[1 : OCCUPIED_LOTS + 1]:
        for slot in range(BOOKINGS_PER_LOT):
            add_booking(session, lot, renter_id, start + timedelta(days=slot * 6))
    for lot in lots[1 : BLOCKS + 1]:
        session.add(
            OccupancyRecord(
                tenant_id=tenant.id,
                lot_id=lot.id,
                kind="block",
                period=Range(
                    start + timedelta(days=SCHEDULE_DAYS - 1), start + timedelta(days=SCHEDULE_DAYS)
                ),
                status="active",
                reason="Benchmark maintenance",
                created_by=owner_id,
            )
        )
    return lots[0], renter_id


async def measure(
    name: str, get: Callable[[], Awaitable[Response]], validate: Callable[[Response], None]
) -> tuple[float, float]:
    samples = []
    for index in range(WARMUP + SAMPLES):
        before = perf_counter()
        response = await get()
        elapsed_ms = (perf_counter() - before) * 1000
        if response.status_code != 200 or response.headers.get("Cache-Control") != "no-store":
            raise SystemExit(f"{name} returned an unexpected response ({response.status_code})")
        if index == 0:
            validate(response)
        if index >= WARMUP:
            samples.append(elapsed_ms)

    p95 = sorted(samples)[ceil(0.95 * len(samples)) - 1]
    maximum = max(samples)
    print(f"{name}: median {median(samples):.2f} ms, p95 {p95:.2f} ms, max {maximum:.2f} ms")
    return p95, maximum


def check_schedule(response: Response) -> None:
    body = response.json()
    occupied = {interval["lot_id"] for interval in body["intervals"]}
    kinds = Counter(interval["kind"] for interval in body["intervals"])
    lot_ids = {lot["id"] for lot in body["lots"]}
    if (
        len(lot_ids) != LOTS
        or not occupied <= lot_ids
        or len(lot_ids - occupied) != LOTS - OCCUPIED_LOTS
        or kinds != {"rental": OCCUPIED_LOTS * BOOKINGS_PER_LOT, "block": BLOCKS}
        or len(body["battery_stock"]) != 1
        or body["battery_stock"][0]["peak_committed"] != OCCUPIED_LOTS
    ):
        raise SystemExit("Schedule did not return the expected lots, intervals, and battery peak")


def check_quote(response: Response) -> None:
    variants = response.json()["variants"]
    available = {item["battery_count"] for item in variants if item["available"]}
    unavailable = {
        item["battery_count"]: item["unavailable_reason"]
        for item in variants
        if not item["available"]
    }
    if (
        len(variants) != VARIANTS
        or available != set(range(FREE_BATTERIES + 1))
        or unavailable != dict.fromkeys(range(FREE_BATTERIES + 1, VARIANTS), "battery_unavailable")
    ):
        raise SystemExit("Quote did not return the expected variants and battery availability")


def check_occupied_quote(response: Response) -> None:
    variants = response.json()["variants"]
    if len(variants) != VARIANTS or any(
        item["available"] or item["unavailable_reason"] != "slot_taken" for item in variants
    ):
        raise SystemExit("Quote did not mark all variants as occupied")


async def main() -> None:
    database_url = os.getenv("BOOKING_BENCHMARK_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "Set BOOKING_BENCHMARK_DATABASE_URL to a migrated disposable PostgreSQL database"
        )

    slug = f"booking-benchmark-{uuid4().hex[:12]}"
    tenant = Tenant(id=uuid4(), slug=slug, name=slug, domain=f"{slug}.test", timezone="UTC")
    owner_id = uuid4()
    start = datetime.combine(datetime.now(UTC).date() + timedelta(days=1), time.min, tzinfo=UTC)
    end = start + timedelta(days=SCHEDULE_DAYS)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        app_env="test",
        database_role="keep_rollin_app",
        jwt_secret=uuid4().hex + uuid4().hex,
    )
    token = JwtTokenService(secret=settings.jwt_secret).create_access(
        user_id=owner_id, tenant_id=tenant.id, role="owner", token_version=1
    )
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            quote_lot, renter_id = await seed(session, tenant, owner_id, start, settings.jwt_secret)

        application = create_app(settings)
        logging.getLogger("app.access").setLevel(logging.WARNING)
        print(f"{SAMPLES} sequential requests per endpoint after {WARMUP} warm-up requests")
        transport = ASGITransport(app=application)
        async with (
            application.router.lifespan_context(application),
            AsyncClient(transport=transport, base_url=f"https://{tenant.domain}") as client,
        ):
            _, schedule_max = await measure(
                "Schedule",
                lambda: client.get(
                    "/api/v1/admin/schedule",
                    params={"from": start.date().isoformat(), "to": end.date().isoformat()},
                    headers={"Authorization": f"Bearer {token}"},
                ),
                check_schedule,
            )

            async def get_quote() -> Response:
                return await client.get(
                    f"/api/v1/public/lots/{QUOTE_SLUG}/quote",
                    params={"start": start.isoformat(), "end": end.isoformat()},
                )

            capacity_p95, _ = await measure("Quote (shared capacity)", get_quote, check_quote)
            async with sessions.begin() as session:
                for slot in range(QUOTE_OCCUPANCY):
                    add_booking(session, quote_lot, renter_id, start + timedelta(hours=slot))
            occupied_p95, _ = await measure("Quote (occupied lot)", get_quote, check_occupied_quote)
        if schedule_max > SCHEDULE_LIMIT_MS or max(capacity_p95, occupied_p95) > QUOTE_P95_LIMIT_MS:
            raise SystemExit(
                f"Budget exceeded (schedule max {SCHEDULE_LIMIT_MS} ms, "
                f"quote p95 {QUOTE_P95_LIMIT_MS} ms)"
            )
    finally:
        try:
            async with sessions.begin() as session:
                await session.execute(delete(Tenant).where(Tenant.id == tenant.id))
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
