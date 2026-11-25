from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import Range

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)

START = datetime(2026, 1, 1, 10, tzinfo=UTC)
END = datetime(2026, 1, 2, 10, tzinfo=UTC)


@dataclass(frozen=True)
class SeededAvailability:
    domain_a: str
    domain_b: str
    tenant_a: UUID
    tenant_b: UUID
    lot_a: UUID
    strict_lot: UUID
    slug: str
    strict_slug: str
    tenant_ids: tuple[UUID, UUID]


def seed_catalog() -> SeededAvailability:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    tenant_a = Tenant(
        id=uuid4(),
        name="Availability A",
        slug=f"availability-a-{suffix}",
        domain=f"availability-a-{suffix}.test",
        subdomain=f"availability-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Availability B",
        slug=f"availability-b-{suffix}",
        domain=f"availability-b-{suffix}.test",
        subdomain=f"availability-b-{suffix}",
        currency="USD",
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
        slug=f"urban-one-{suffix}",
        name="Urban One",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1, 7],
        status="active",
        version=1,
    )
    strict_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"weekly-{suffix}",
        name="Weekly",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[7],
        status="active",
        version=1,
    )
    lot_b = LotRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        category_id=category_b.id,
        slug=lot_a.slug,
        name="Urban One B",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1],
        status="active",
        version=1,
    )
    variant_a = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        battery_count=1,
        is_active=True,
    )
    inactive_variant = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        battery_count=2,
        is_active=False,
    )
    variant_strict = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=strict_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_b = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        lot_id=lot_b.id,
        battery_count=1,
        is_active=True,
    )

    async def seed() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add_all([tenant_a, tenant_b])
                await session.flush()
                session.add_all([category_a, category_b])
                await session.flush()
                session.add_all([lot_a, strict_lot, lot_b])
                await session.flush()
                session.add_all([variant_a, inactive_variant, variant_strict, variant_b])
                await session.flush()
                session.add_all(
                    [
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_a.id,
                            min_units=1,
                            price_per_unit_minor=50000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_a.id,
                            min_units=7,
                            price_per_unit_minor=40000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=inactive_variant.id,
                            min_units=1,
                            price_per_unit_minor=90000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_strict.id,
                            min_units=7,
                            price_per_unit_minor=30000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_b.id,
                            variant_id=variant_b.id,
                            min_units=1,
                            price_per_unit_minor=10000,
                        ),
                    ]
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return SeededAvailability(
        domain_a=tenant_a.domain,
        domain_b=tenant_b.domain,
        tenant_a=tenant_a.id,
        tenant_b=tenant_b.id,
        lot_a=lot_a.id,
        strict_lot=strict_lot.id,
        slug=lot_a.slug,
        strict_slug=strict_lot.slug,
        tenant_ids=(tenant_a.id, tenant_b.id),
    )


def cleanup_catalog(tenant_ids: tuple[UUID, UUID]) -> None:
    assert DATABASE_URL is not None

    async def cleanup() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(cleanup())


def add_occupancy(
    *,
    tenant_id: UUID,
    lot_id: UUID,
    start: datetime,
    end: datetime,
    kind: str = "booking",
) -> None:
    assert DATABASE_URL is not None

    async def insert() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add(
                    OccupancyRecord(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        lot_id=lot_id,
                        kind=kind,
                        period=Range(start, end, bounds="[)"),
                        ref_id=None,
                        status="active",
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(insert())


@pytest.fixture
def seeded() -> Iterator[SeededAvailability]:
    value = seed_catalog()
    try:
        yield value
    finally:
        cleanup_catalog(value.tenant_ids)


def client_for(domain: str) -> TestClient:
    assert DATABASE_URL is not None
    settings = Settings(
        database_url=DATABASE_URL,
        app_env="test",
        platform_domain="platform.test",
        allow_tenant_header=True,
        database_role="keep_rollin_app",
    )
    return TestClient(create_app(settings), base_url=f"http://{domain}")


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_availability_is_free_and_has_next_free(seeded: SeededAvailability) -> None:
    with client_for(seeded.domain_a) as client:
        response = client.get(
            f"/api/v1/public/lots/{seeded.slug}/availability",
            params={"from": _iso(START), "to": _iso(END)},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["lot_id"] == str(seeded.lot_a)
    assert _parse(payload["from"]) == START
    assert _parse(payload["to"]) == END
    assert payload["busy"] == []
    assert _parse(payload["next_free"]["start"]) == START
    assert _parse(payload["next_free"]["end"]) == END
    assert response.headers["cache-control"] == "no-store"


def test_availability_masks_kind_and_computes_first_gap(seeded: SeededAvailability) -> None:
    occupied_start = START + timedelta(hours=2)
    occupied_end = START + timedelta(hours=4)
    add_occupancy(
        tenant_id=seeded.tenant_a,
        lot_id=seeded.lot_a,
        start=occupied_start,
        end=occupied_end,
        kind="maintenance",
    )

    with client_for(seeded.domain_a) as client:
        response = client.get(
            f"/api/v1/public/lots/{seeded.slug}/availability",
            params={"from": _iso(START), "to": _iso(END)},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["busy"] == [
        {
            "start": occupied_start.isoformat().replace("+00:00", "Z"),
            "end": occupied_end.isoformat().replace("+00:00", "Z"),
            "kind": "busy",
        }
    ]
    assert _parse(payload["next_free"]["start"]) == START
    assert _parse(payload["next_free"]["end"]) == occupied_start


def test_availability_rejects_invalid_ranges(seeded: SeededAvailability) -> None:
    with client_for(seeded.domain_a) as client:
        naive = client.get(
            f"/api/v1/public/lots/{seeded.slug}/availability",
            params={"from": "2026-01-01T10:00:00", "to": _iso(END)},
        )
        reversed_range = client.get(
            f"/api/v1/public/lots/{seeded.slug}/availability",
            params={"from": _iso(END), "to": _iso(START)},
        )
        too_long = client.get(
            f"/api/v1/public/lots/{seeded.slug}/availability",
            params={"from": _iso(START), "to": _iso(START + timedelta(days=91))},
        )

    for response in (naive, reversed_range, too_long):
        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["code"] == "validation_error"


def test_availability_returns_404_for_missing_lot(seeded: SeededAvailability) -> None:
    with client_for(seeded.domain_a) as client:
        response = client.get(
            "/api/v1/public/lots/missing-slug/availability",
            params={"from": _iso(START), "to": _iso(END)},
        )

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_found"


def test_availability_is_tenant_scoped(seeded: SeededAvailability) -> None:
    add_occupancy(
        tenant_id=seeded.tenant_a,
        lot_id=seeded.lot_a,
        start=START,
        end=END,
    )
    with client_for(seeded.domain_b) as client:
        response = client.get(
            f"/api/v1/public/lots/{seeded.slug}/availability",
            params={"from": _iso(START), "to": _iso(END)},
        )

    assert response.status_code == 200
    assert response.json()["busy"] == []


def test_quote_returns_contract_price_and_no_store(seeded: SeededAvailability) -> None:
    with client_for(seeded.domain_a) as client:
        one_day = client.get(
            f"/api/v1/public/lots/{seeded.slug}/quote",
            params={"start": _iso(START), "end": _iso(END)},
        )
        seven_days = client.get(
            f"/api/v1/public/lots/{seeded.slug}/quote",
            params={"start": _iso(START), "end": _iso(START + timedelta(days=7))},
        )

    assert one_day.status_code == 200
    first = one_day.json()
    assert first["units"] == 1
    assert first["rental_unit"] == "day"
    assert first["variants"] == [
        {
            "variant_id": first["variants"][0]["variant_id"],
            "battery_count": 1,
            "price_total_minor": 50000,
            "currency": "RUB",
            "tier_min_units": 1,
            "available": True,
            "unavailable_reason": None,
        }
    ]
    assert one_day.headers["cache-control"] == "no-store"

    assert seven_days.status_code == 200
    second = seven_days.json()
    assert second["units"] == 7
    assert second["variants"][0]["price_total_minor"] == 280000
    assert second["variants"][0]["tier_min_units"] == 7


def test_quote_marks_occupied_slot_and_rounds_units(seeded: SeededAvailability) -> None:
    add_occupancy(
        tenant_id=seeded.tenant_a,
        lot_id=seeded.lot_a,
        start=START,
        end=START + timedelta(hours=2),
    )
    with client_for(seeded.domain_a) as client:
        response = client.get(
            f"/api/v1/public/lots/{seeded.slug}/quote",
            params={"start": _iso(START), "end": _iso(START + timedelta(hours=25))},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["units"] == 2
    assert payload["variants"][0]["available"] is False
    assert payload["variants"][0]["unavailable_reason"] == "slot_taken"
    assert payload["variants"][0]["price_total_minor"] == 100000


def test_quote_rejects_below_minimum_and_missing_lot(seeded: SeededAvailability) -> None:
    with client_for(seeded.domain_a) as client:
        below_minimum = client.get(
            f"/api/v1/public/lots/{seeded.strict_slug}/quote",
            params={"start": _iso(START), "end": _iso(END)},
        )
        missing = client.get(
            "/api/v1/public/lots/missing-slug/quote",
            params={"start": _iso(START), "end": _iso(END)},
        )

    assert below_minimum.status_code == 422
    assert below_minimum.headers["content-type"] == "application/problem+json"
    assert below_minimum.json()["code"] == "rental_period_not_allowed"
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


def test_quote_uses_tenant_currency(seeded: SeededAvailability) -> None:
    with client_for(seeded.domain_b) as client:
        response = client.get(
            f"/api/v1/public/lots/{seeded.slug}/quote",
            params={"start": _iso(START), "end": _iso(END)},
        )

    assert response.status_code == 200
    assert response.json()["variants"][0]["currency"] == "USD"
    assert response.json()["variants"][0]["price_total_minor"] == 10000
