from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import Range

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.characteristic_record import CharacteristicRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SeededCatalog:
    domain_a: str
    domain_b: str
    category_a: UUID
    lot_a: UUID
    lot_metro: UUID
    active_slug: str
    metro_slug: str
    archived_slug: str
    archived_category_slug: str
    unbookable_slug: str
    broken_slug: str
    tierless_slug: str
    mismatched_battery_slug: str
    empty_durations_slug: str
    empty_battery_type_slug: str
    bad_durations_slug: str
    growing_tiers_slug: str
    tenant_ids: tuple[UUID, UUID]


def seed_catalog() -> SeededCatalog:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    tenant_a = Tenant(
        id=uuid4(),
        name="API Catalog A",
        slug=f"api-catalog-a-{suffix}",
        domain=f"api-catalog-a-{suffix}.test",
        subdomain=f"api-catalog-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="API Catalog B",
        slug=f"api-catalog-b-{suffix}",
        domain=f"api-catalog-b-{suffix}.test",
        subdomain=f"api-catalog-b-{suffix}",
        currency="USD",
    )
    category_a = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        name="E-bikes",
        slug=f"ebikes-{suffix}",
        description="Electric bikes",
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
    archived_category = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        name="Old bikes",
        slug=f"old-{suffix}",
        description=None,
        is_archived=True,
    )
    lot_a = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"urban-one-{suffix}",
        name="Urban One",
        description="City bike",
        photos=["https://example.com/urban.jpg"],
        characteristics={"power": 500},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1, 7],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    lot_metro = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"metro-{suffix}",
        name="Metro",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    archived_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"archived-{suffix}",
        name="Archived",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1],
        status="archived",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    archived_category_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=archived_category.id,
        slug=f"old-lot-{suffix}",
        name="Old lot",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    unbookable_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"draft-{suffix}",
        name="Draft",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    broken_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"broken-{suffix}",
        name="Broken",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type=None,
        allowed_durations=[1],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    tierless_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"tierless-{suffix}",
        name="Tierless",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    mismatched_battery_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"battery-{suffix}",
        name="Battery mismatch",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type=None,
        allowed_durations=[1],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    empty_durations_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"durations-{suffix}",
        name="Empty durations",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    empty_battery_type_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"empty-type-{suffix}",
        name="Empty battery type",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="",
        allowed_durations=[1],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    bad_durations_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"bad-durations-{suffix}",
        name="Bad durations",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[0],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    growing_tiers_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"growing-{suffix}",
        name="Growing tiers",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1, 7],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
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
        created_at=NOW,
        updated_at=NOW,
    )
    variant_a = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        battery_count=1,
        is_active=True,
    )
    variant_metro = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_metro.id,
        battery_count=1,
        is_active=True,
    )
    variant_archived = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=archived_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_archived_category = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=archived_category_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_unbookable = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=unbookable_lot.id,
        battery_count=1,
        is_active=False,
    )
    variant_b = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        lot_id=lot_b.id,
        battery_count=1,
        is_active=True,
    )
    variant_tierless = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=tierless_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_mismatched_battery = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=mismatched_battery_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_empty_durations = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=empty_durations_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_empty_battery_type = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=empty_battery_type_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_bad_durations = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=bad_durations_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_growing_tiers = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=growing_tiers_lot.id,
        battery_count=1,
        is_active=True,
    )
    characteristic = CharacteristicRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        code="power",
        name="Power",
        type="number",
        unit="W",
        is_required=False,
        options=[],
        sort=1,
        is_archived=False,
    )
    archived_characteristic = CharacteristicRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        code="legacy",
        name="Legacy",
        type="text",
        unit=None,
        is_required=False,
        options=[],
        sort=2,
        is_archived=True,
    )

    async def seed() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add_all([tenant_a, tenant_b])
                await session.flush()
                session.add_all([category_a, category_b, archived_category])
                await session.flush()
                session.add_all(
                    [
                        lot_a,
                        lot_metro,
                        archived_lot,
                        archived_category_lot,
                        unbookable_lot,
                        broken_lot,
                        tierless_lot,
                        mismatched_battery_lot,
                        empty_durations_lot,
                        empty_battery_type_lot,
                        bad_durations_lot,
                        growing_tiers_lot,
                        lot_b,
                    ]
                )
                await session.flush()
                session.add_all(
                    [
                        variant_a,
                        variant_metro,
                        variant_archived,
                        variant_archived_category,
                        variant_unbookable,
                        variant_tierless,
                        variant_mismatched_battery,
                        variant_empty_durations,
                        variant_empty_battery_type,
                        variant_bad_durations,
                        variant_growing_tiers,
                        variant_b,
                    ]
                )
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
                            variant_id=variant_metro.id,
                            min_units=1,
                            price_per_unit_minor=30000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_archived.id,
                            min_units=1,
                            price_per_unit_minor=20000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_archived_category.id,
                            min_units=1,
                            price_per_unit_minor=25000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_unbookable.id,
                            min_units=1,
                            price_per_unit_minor=60000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_mismatched_battery.id,
                            min_units=1,
                            price_per_unit_minor=45000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_empty_durations.id,
                            min_units=1,
                            price_per_unit_minor=35000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_empty_battery_type.id,
                            min_units=1,
                            price_per_unit_minor=36000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_bad_durations.id,
                            min_units=1,
                            price_per_unit_minor=37000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_growing_tiers.id,
                            min_units=1,
                            price_per_unit_minor=50000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_a.id,
                            variant_id=variant_growing_tiers.id,
                            min_units=7,
                            price_per_unit_minor=60000,
                        ),
                        LotPriceTierRecord(
                            id=uuid4(),
                            tenant_id=tenant_b.id,
                            variant_id=variant_b.id,
                            min_units=1,
                            price_per_unit_minor=10000,
                        ),
                        characteristic,
                        archived_characteristic,
                    ]
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return SeededCatalog(
        domain_a=tenant_a.domain,
        domain_b=tenant_b.domain,
        category_a=category_a.id,
        lot_a=lot_a.id,
        lot_metro=lot_metro.id,
        active_slug=lot_a.slug,
        metro_slug=lot_metro.slug,
        archived_slug=archived_lot.slug,
        archived_category_slug=archived_category_lot.slug,
        unbookable_slug=unbookable_lot.slug,
        broken_slug=broken_lot.slug,
        tierless_slug=tierless_lot.slug,
        mismatched_battery_slug=mismatched_battery_lot.slug,
        empty_durations_slug=empty_durations_lot.slug,
        empty_battery_type_slug=empty_battery_type_lot.slug,
        bad_durations_slug=bad_durations_lot.slug,
        growing_tiers_slug=growing_tiers_lot.slug,
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


@pytest.fixture
def seeded_catalog() -> Iterator[SeededCatalog]:
    seeded = seed_catalog()
    try:
        yield seeded
    finally:
        cleanup_catalog(seeded.tenant_ids)


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


def test_public_categories(seeded_catalog: SeededCatalog) -> None:
    with client_for(seeded_catalog.domain_a) as client:
        response = client.get("/api/v1/public/categories")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "E-bikes"
    assert payload[0]["characteristics"] == [
        {
            "id": payload[0]["characteristics"][0]["id"],
            "code": "power",
            "name": "Power",
            "type": "number",
            "unit": "W",
            "is_required": False,
            "options": [],
            "sort": 1,
        }
    ]


def test_public_lots_filter_by_query(seeded_catalog: SeededCatalog) -> None:
    with client_for(seeded_catalog.domain_a) as client:
        filtered = client.get(
            "/api/v1/public/lots",
            params={"category_id": str(seeded_catalog.category_a), "q": "Urban", "limit": 1},
        )

    assert filtered.status_code == 200
    payload = filtered.json()
    assert payload["total"] == 1
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["items"][0]["price_from"] == {
        "amount_minor": 40000,
        "per": "day",
        "at_units": 7,
        "battery_count": 1,
    }


def test_public_lots_paginates_and_accepts_empty_query(
    seeded_catalog: SeededCatalog,
) -> None:
    seen: list[str] = []
    with client_for(seeded_catalog.domain_a) as client:
        for offset in (0, 1, 2):
            response = client.get(
                "/api/v1/public/lots",
                params={"q": "", "limit": 1, "offset": offset},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["total"] == 3
            assert len(payload["items"]) == 1
            seen.append(payload["items"][0]["id"])

    assert len(set(seen)) == 3
    assert seen == sorted(seen, reverse=True)


def test_public_lots_rejects_nul_query_and_out_of_range_offset(
    seeded_catalog: SeededCatalog,
) -> None:
    with client_for(seeded_catalog.domain_a) as client:
        nul_query = client.get("/api/v1/public/lots", params={"q": "\x00"})
        huge_offset = client.get(
            "/api/v1/public/lots",
            params={"offset": MAX_DATABASE_INTEGER + 1},
        )

    assert nul_query.status_code == 422
    assert huge_offset.status_code == 422


def test_public_lot_detail_and_hidden_lots(seeded_catalog: SeededCatalog) -> None:
    with client_for(seeded_catalog.domain_a) as client:
        active = client.get(f"/api/v1/public/lots/{seeded_catalog.active_slug}")
        archived = client.get(f"/api/v1/public/lots/{seeded_catalog.archived_slug}")
        archived_category = client.get(
            f"/api/v1/public/lots/{seeded_catalog.archived_category_slug}"
        )
        unbookable = client.get(f"/api/v1/public/lots/{seeded_catalog.unbookable_slug}")
        broken = client.get(f"/api/v1/public/lots/{seeded_catalog.broken_slug}")
        tierless = client.get(f"/api/v1/public/lots/{seeded_catalog.tierless_slug}")
        mismatched_battery = client.get(
            f"/api/v1/public/lots/{seeded_catalog.mismatched_battery_slug}"
        )
        empty_durations = client.get(f"/api/v1/public/lots/{seeded_catalog.empty_durations_slug}")
        empty_battery_type = client.get(
            f"/api/v1/public/lots/{seeded_catalog.empty_battery_type_slug}"
        )
        bad_durations = client.get(f"/api/v1/public/lots/{seeded_catalog.bad_durations_slug}")
        growing_tiers = client.get(f"/api/v1/public/lots/{seeded_catalog.growing_tiers_slug}")
        invalid_slug = client.get("/api/v1/public/lots/Invalid_Slug")
        missing = client.get("/api/v1/public/lots/missing-slug")

    assert active.status_code == 200
    assert active.json()["id"] == str(seeded_catalog.lot_a)
    assert active.json()["is_bookable"] is True
    assert active.json()["currency"] == "RUB"
    assert archived.status_code == 404
    assert archived_category.status_code == 404
    assert unbookable.status_code == 404
    assert broken.status_code == 404
    assert tierless.status_code == 404
    assert mismatched_battery.status_code == 404
    assert empty_durations.status_code == 404
    assert empty_battery_type.status_code == 404
    assert bad_durations.status_code == 404
    assert growing_tiers.status_code == 404
    assert invalid_slug.status_code == 404
    assert missing.status_code == 404
    assert missing.headers["content-type"] == "application/problem+json"
    assert missing.json()["code"] == "not_found"


def test_public_lot_detail_uses_tenant_scope_and_currency(
    seeded_catalog: SeededCatalog,
) -> None:
    with client_for(seeded_catalog.domain_b) as client:
        detail = client.get(f"/api/v1/public/lots/{seeded_catalog.active_slug}")
        listed = client.get("/api/v1/public/lots")

    assert detail.status_code == 200
    assert detail.json()["name"] == "Urban One B"
    assert detail.json()["currency"] == "USD"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_public_lots_filters_each_characteristic_by_its_category_definition(
    seeded_catalog: SeededCatalog,
) -> None:
    assert DATABASE_URL is not None
    other_category = uuid4()
    tenant_id = seeded_catalog.tenant_ids[0]
    label = 'Сити, "Плюс"'

    async def seed_characteristics() -> None:
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine)() as session:
                session.add(
                    CategoryRecord(
                        id=other_category,
                        tenant_id=tenant_id,
                        name="Text-power category",
                        slug="text-power-category",
                    )
                )
                await session.flush()
                session.add_all(
                    [
                        CharacteristicRecord(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            category_id=other_category,
                            code="power",
                            name="Power text",
                            type="text",
                        ),
                        CharacteristicRecord(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            category_id=seeded_catalog.category_a,
                            code="label",
                            name="Label",
                            type="text",
                        ),
                        CharacteristicRecord(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            category_id=seeded_catalog.category_a,
                            code="color",
                            name="Color",
                            type="select",
                            options=["Red", "Blue"],
                        ),
                    ]
                )
                await session.execute(
                    update(LotRecord)
                    .where(LotRecord.id == seeded_catalog.lot_a)
                    .values(characteristics={"power": 500, "label": label, "color": "Red"})
                )
                await session.execute(
                    update(LotRecord)
                    .where(LotRecord.id == seeded_catalog.lot_metro)
                    .values(category_id=other_category, characteristics={"power": "500"})
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed_characteristics())
    with client_for(seeded_catalog.domain_a) as client:
        url = "/api/v1/public/lots"
        mixed = client.get(url, params={"char_power": "500", "limit": 1})
        assert mixed.status_code == 200
        assert mixed.json()["total"] == 2
        assert len(mixed.json()["items"]) == 1
        past_end = client.get(url, params={"char_power": "500", "offset": 2})
        assert past_end.json() == {"total": 2, "limit": 20, "offset": 2, "items": []}

        combined = client.get(
            url,
            params={"char_power": "5e2", "char_label": label, "char_color": "Red"},
        )
        assert combined.status_code == 200
        assert [lot["id"] for lot in combined.json()["items"]] == [str(seeded_catalog.lot_a)]
        case_mismatch = client.get(url, params={"char_label": label.lower()})
        assert case_mismatch.status_code == 200
        assert case_mismatch.json()["total"] == 0

        invalid_option = client.get(url, params={"char_color": "red"})
        assert invalid_option.status_code == 422
        assert "char_color" in invalid_option.json()["fields"]
        wrong_category = client.get(
            url, params={"category_id": str(other_category), "char_label": label}
        )
        assert wrong_category.status_code == 422
        assert "char_label" in wrong_category.json()["fields"]


def test_public_lots_rejects_invalid_characteristic_filters(seeded_catalog: SeededCatalog) -> None:
    with client_for(seeded_catalog.domain_a) as client:
        for field, value in [
            ("char_missing", "500"),
            ("char_legacy", "500"),
            ("char_", "500"),
            ("char_power", ""),
            ("char_power", "  "),
            ("char_power", "500\x00"),
            ("char_power", "NaN"),
            ("char_power", "Infinity"),
            ("char_power", "1e309"),
            ("char_power", "1e-16384"),
        ]:
            response = client.get(
                "/api/v1/public/lots",
                params={field: value},
                headers={"If-None-Match": "*"},
            )
            assert response.status_code == 422, (field, value, response.text)
            assert field in response.json()["fields"]
        repeated = client.get(
            "/api/v1/public/lots",
            params=[("char_power", "500"), ("char_power", "500")],
        )
        assert repeated.status_code == 422
        assert repeated.json()["fields"]["char_power"] == "duplicate characteristic filter"

        foreign = client.get(
            "/api/v1/public/lots",
            params={"char_power": "500"},
            headers={"X-Tenant": seeded_catalog.domain_b},
        )
        assert foreign.status_code == 422


def test_public_lots_sorts_using_active_minimum_price(seeded_catalog: SeededCatalog) -> None:
    with client_for(seeded_catalog.domain_a) as client:
        for order, expected_names in [
            ("name_asc", ["Draft", "Metro", "Urban One"]),
            ("price_asc", ["Metro", "Urban One", "Draft"]),
            ("price_desc", ["Urban One", "Metro", "Draft"]),
        ]:
            response = client.get("/api/v1/public/lots", params={"sort": order})
            assert response.status_code == 200
            assert [lot["name"] for lot in response.json()["items"]] == expected_names
        invalid = client.get("/api/v1/public/lots", params={"sort": "price"})
        assert invalid.status_code == 422


def test_public_lots_filters_period_and_revalidates_after_occupancy_change(
    seeded_catalog: SeededCatalog,
) -> None:
    assert DATABASE_URL is not None
    start = NOW + timedelta(days=2)
    end = start + timedelta(hours=1)
    params = {"available_from": start.isoformat(), "available_to": end.isoformat()}

    async def seed_occupancy() -> None:
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine)() as session:
                for lot_id, interval, status in [
                    (seeded_catalog.lot_a, Range(start, end), "active"),
                    (seeded_catalog.lot_metro, Range(NOW, start), "active"),
                    (seeded_catalog.lot_metro, Range(start, end), "released"),
                    (seeded_catalog.lot_metro, Range(end, end + timedelta(days=1)), "active"),
                ]:
                    session.add(
                        OccupancyRecord(
                            tenant_id=seeded_catalog.tenant_ids[0],
                            lot_id=lot_id,
                            kind="block",
                            period=interval,
                            status=status,
                        )
                    )
                await session.commit()
        finally:
            await engine.dispose()

    with client_for(seeded_catalog.domain_a) as client:
        url = "/api/v1/public/lots"
        before = client.get(url, params=params)
        assert before.status_code == 200
        assert {lot["slug"] for lot in before.json()["items"]} == {
            seeded_catalog.active_slug,
            seeded_catalog.metro_slug,
        }
        asyncio.run(seed_occupancy())

        after = client.get(url, params=params, headers={"If-None-Match": before.headers["ETag"]})
        assert after.status_code == 200
        assert after.headers["ETag"] != before.headers["ETag"]
        assert after.json()["total"] == 1
        assert [lot["slug"] for lot in after.json()["items"]] == [seeded_catalog.metro_slug]


def test_public_lots_validates_both_period_bounds(seeded_catalog: SeededCatalog) -> None:
    with client_for(seeded_catalog.domain_a) as client:
        url = "/api/v1/public/lots"
        for params in [
            {"available_from": "2026-01-01T00:00:00Z"},
            {"available_to": "2026-01-01T00:00:00Z"},
            {"available_from": "2026-01-01T00:00:00", "available_to": "2026-01-02T00:00:00Z"},
            {"available_from": "2026-01-02T00:00:00Z", "available_to": "2026-01-01T00:00:00Z"},
            {"available_from": "2026-01-01T00:00:00Z", "available_to": "2026-04-01T00:00:01Z"},
            {
                "available_from": "0001-01-01T00:00:00+01:00",
                "available_to": "0001-01-02T00:00:00+01:00",
            },
        ]:
            response = client.get(url, params=params, headers={"If-None-Match": "*"})
            assert response.status_code == 422, (params, response.text)
        exact = client.get(
            url,
            params={
                "available_from": "2026-01-01T01:00:00+01:00",
                "available_to": "2026-04-01T00:00:00Z",
            },
        )
        assert exact.status_code == 200


def test_public_catalog_conditional_reads_resolve_tenant_and_representation(
    seeded_catalog: SeededCatalog,
) -> None:
    with client_for(seeded_catalog.domain_a) as client:
        for path in ("categories", "lots", f"lots/{seeded_catalog.active_slug}"):
            url = f"/api/v1/public/{path}"
            initial = client.get(url)
            assert initial.status_code == 200
            tag = initial.headers["ETag"]
            assert tag.startswith('W/"')
            assert (
                initial.headers["Cache-Control"] == "public, max-age=60, stale-while-revalidate=300"
            )
            assert initial.headers["Vary"] == "X-Tenant"

            conditional = client.get(
                url, headers=[("If-None-Match", 'W/"non,matching"'), ("If-None-Match", tag[2:])]
            )
            assert conditional.status_code == 304
            assert conditional.content == b""
            for name in ("ETag", "Cache-Control", "Vary"):
                assert conditional.headers[name] == initial.headers[name]
            assert client.get(url, headers={"If-None-Match": "*"}).status_code == 304

            elsewhere = client.get(
                url,
                headers={"If-None-Match": tag, "X-Tenant": seeded_catalog.domain_b},
            )
            assert elsewhere.status_code == 200
            assert elsewhere.headers["ETag"] != tag

        missing = client.get("/api/v1/public/lots/missing", headers={"If-None-Match": "*"})
        assert missing.status_code == 404


def test_public_lots_rejects_unknown_query_filter(seeded_catalog: SeededCatalog) -> None:
    with client_for(seeded_catalog.domain_a) as client:
        response = client.get("/api/v1/public/lots", params={"price_max": "100"})
    assert response.status_code == 422
    assert response.json()["fields"] == {"price_max": "unknown filter"}
