import asyncio
from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import Range

from app.db import create_engine, create_session_factory
from app.models import User
from src.infrastructure.postgres.models.battery_stock_record import BatteryStockRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from tests.api.test_availability_api import (
    DATABASE_URL,
    END,
    START,
    SeededAvailability,
    add_occupancy,
    cleanup_catalog,
    client_for,
    seed_catalog,
)

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")


@pytest.fixture
def seeded() -> Iterator[SeededAvailability]:
    value = seed_catalog()
    try:
        yield value
    finally:
        cleanup_catalog(value.tenant_ids)


def test_quote_missing_stock_leaves_only_zero_battery_variants_available(
    seeded: SeededAvailability,
) -> None:
    assert DATABASE_URL is not None

    async def seed_without_stock() -> None:
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine)() as session:
                await session.execute(
                    delete(BatteryStockRecord).where(
                        BatteryStockRecord.tenant_id == seeded.tenant_a
                    )
                )
                zero_battery_variant = LotVariantRecord(
                    id=uuid4(), tenant_id=seeded.tenant_a, lot_id=seeded.lot_a, battery_count=0
                )
                session.add(zero_battery_variant)
                await session.flush()
                session.add(
                    LotPriceTierRecord(
                        id=uuid4(),
                        tenant_id=seeded.tenant_a,
                        variant_id=zero_battery_variant.id,
                        min_units=1,
                        price_per_unit_minor=40000,
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed_without_stock())
    query = {"start": START.isoformat(), "end": END.isoformat()}
    path = f"/api/v1/public/lots/{seeded.slug}/quote"
    with client_for(seeded.domain_a) as client:
        response = client.get(path, params=query)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        variants = {variant["battery_count"]: variant for variant in response.json()["variants"]}
        assert variants[0]["available"] is True
        assert variants[0]["unavailable_reason"] is None
        assert variants[1]["available"] is False
        assert variants[1]["unavailable_reason"] == "battery_unavailable"
        assert variants[1]["price_total_minor"] == 50000

        add_occupancy(
            tenant_id=seeded.tenant_a, lot_id=seeded.lot_a, start=START, end=END, kind="block"
        )
        occupied = client.get(path, params=query)
        assert occupied.status_code == 200, occupied.text
        assert {item["unavailable_reason"] for item in occupied.json()["variants"]} == {
            "slot_taken"
        }

    with client_for(seeded.domain_b) as client:
        foreign = client.get(path, params=query)
        assert foreign.status_code == 200, foreign.text
        assert foreign.json()["variants"][0]["available"] is True


def test_quote_uses_the_shared_half_open_peak_across_lots(seeded: SeededAvailability) -> None:
    assert DATABASE_URL is not None

    async def seed_reservations() -> None:
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine)() as session:
                second_variant = await session.scalar(
                    select(LotVariantRecord).where(
                        LotVariantRecord.lot_id == seeded.lot_a,
                        LotVariantRecord.battery_count == 2,
                    )
                )
                assert second_variant is not None
                second_variant.is_active = True
                renter = User(
                    id=uuid4(),
                    tenant_id=seeded.tenant_a,
                    email="quote-renter@example.test",
                    name="Quote renter",
                    role="user",
                )
                session.add(renter)
                await session.flush()
                for start, end in ((START, END), (END, END + timedelta(days=1))):
                    rental_id, occupancy_id = uuid4(), uuid4()
                    session.add(
                        OccupancyRecord(
                            id=occupancy_id,
                            tenant_id=seeded.tenant_a,
                            lot_id=seeded.strict_lot,
                            kind="booking",
                            period=Range(start, end, bounds="[)"),
                            ref_id=rental_id,
                            status="active",
                        )
                    )
                    session.add(
                        RentalRecord(
                            id=rental_id,
                            tenant_id=seeded.tenant_a,
                            user_id=renter.id,
                            lot_id=seeded.strict_lot,
                            variant_id=uuid4(),
                            occupancy_id=occupancy_id,
                            battery_type="48v",
                            battery_count=2,
                            start_time=start,
                            end_time=end,
                            cancellation_deadline=start - timedelta(hours=1),
                            price_minor=50000,
                            currency="RUB",
                            status="booked",
                        )
                    )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed_reservations())
    path = f"/api/v1/public/lots/{seeded.slug}/quote"
    with client_for(seeded.domain_a) as client:
        response = client.get(
            path, params={"start": START.isoformat(), "end": (END + timedelta(days=1)).isoformat()}
        )
        assert response.status_code == 200, response.text
        variants = {variant["battery_count"]: variant for variant in response.json()["variants"]}
        assert variants[1]["available"] is True
        assert variants[2]["available"] is False
        assert variants[2]["unavailable_reason"] == "battery_unavailable"
