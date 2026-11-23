from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant
from src.application.repositories.i_lot_repository import LotListFilters
from src.domain.value_objects.slug import Slug
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.characteristic_record import CharacteristicRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.repositories.category_repository import CategoryRepository
from src.infrastructure.postgres.repositories.lot_repository import LotRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SeededCatalog:
    tenant_a: UUID
    tenant_b: UUID
    category_a: UUID
    category_b: UUID
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
    malformed_json_slug: str
    big_number_slug: str
    fractional_number_slug: str
    empty_name_slug: str
    upper_slug: str
    lot_b: UUID
    variant_b: UUID


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest_asyncio.fixture
async def seeded(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[SeededCatalog]:
    suffix = uuid4().hex[:10]
    tenant_a = Tenant(
        id=uuid4(),
        name="Catalog A",
        slug=f"catalog-a-{suffix}",
        domain=f"catalog-a-{suffix}.test",
        subdomain=f"catalog-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Catalog B",
        slug=f"catalog-b-{suffix}",
        domain=f"catalog-b-{suffix}.test",
        subdomain=f"catalog-b-{suffix}",
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
        slug=f"urban-{suffix}",
        name="Urban",
        description=None,
        photos=[],
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
    malformed_json_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"malformed-{suffix}",
        name="Malformed",
        description=None,
        photos={},
        characteristics=[],
        rental_unit="day",
        battery_type="48v",
        allowed_durations=[1],
        status="active",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    big_number_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"big-number-{suffix}",
        name="Big number",
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
    fractional_number_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"fractional-number-{suffix}",
        name="Fractional number",
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
    empty_name_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"empty-name-{suffix}",
        name="",
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
    upper_slug_lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"Upper-{suffix}",
        name="Upper",
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
    lot_b = LotRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        category_id=category_b.id,
        slug=f"urban-{suffix}",
        name="Urban B",
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
    variant_1 = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        battery_count=1,
        is_active=True,
    )
    variant_2 = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        battery_count=2,
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
    variant_malformed_json = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=malformed_json_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_big_number = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=big_number_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_fractional_number = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=fractional_number_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_empty_name = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=empty_name_lot.id,
        battery_count=1,
        is_active=True,
    )
    variant_upper_slug = LotVariantRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=upper_slug_lot.id,
        battery_count=1,
        is_active=True,
    )
    characteristic_a = CharacteristicRecord(
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

    async with session_factory() as session:
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
                malformed_json_lot,
                big_number_lot,
                fractional_number_lot,
                empty_name_lot,
                upper_slug_lot,
                lot_b,
            ]
        )
        await session.flush()
        session.add_all(
            [
                variant_1,
                variant_2,
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
                variant_malformed_json,
                variant_big_number,
                variant_fractional_number,
                variant_empty_name,
                variant_upper_slug,
                variant_b,
            ]
        )
        await session.flush()
        await session.execute(
            text(
                "UPDATE lot SET characteristics = "
                "jsonb_build_object('big', repeat('9', 4301)::numeric) "
                "WHERE id = :id"
            ),
            {"id": big_number_lot.id},
        )
        await session.execute(
            text(
                "UPDATE lot SET characteristics = "
                "jsonb_build_object('power', ('2' || repeat('0', 308) || '.5')::numeric) "
                "WHERE id = :id"
            ),
            {"id": fractional_number_lot.id},
        )
        session.add_all(
            [
                LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=tenant_a.id,
                    variant_id=variant_1.id,
                    min_units=1,
                    price_per_unit_minor=50000,
                ),
                LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=tenant_a.id,
                    variant_id=variant_1.id,
                    min_units=7,
                    price_per_unit_minor=40000,
                ),
                LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=tenant_a.id,
                    variant_id=variant_2.id,
                    min_units=1,
                    price_per_unit_minor=70000,
                ),
                LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=tenant_a.id,
                    variant_id=variant_2.id,
                    min_units=7,
                    price_per_unit_minor=60000,
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
                    tenant_id=tenant_a.id,
                    variant_id=variant_malformed_json.id,
                    min_units=1,
                    price_per_unit_minor=38000,
                ),
                LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=tenant_a.id,
                    variant_id=variant_big_number.id,
                    min_units=1,
                    price_per_unit_minor=38500,
                ),
                LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=tenant_a.id,
                    variant_id=variant_fractional_number.id,
                    min_units=1,
                    price_per_unit_minor=38750,
                ),
                LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=tenant_a.id,
                    variant_id=variant_empty_name.id,
                    min_units=1,
                    price_per_unit_minor=39000,
                ),
                LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=tenant_a.id,
                    variant_id=variant_upper_slug.id,
                    min_units=1,
                    price_per_unit_minor=41000,
                ),
                LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=tenant_b.id,
                    variant_id=variant_b.id,
                    min_units=1,
                    price_per_unit_minor=10000,
                ),
                characteristic_a,
                archived_characteristic,
            ]
        )
        await session.commit()

    try:
        yield SeededCatalog(
            tenant_a=tenant_a.id,
            tenant_b=tenant_b.id,
            category_a=category_a.id,
            category_b=category_b.id,
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
            malformed_json_slug=malformed_json_lot.slug,
            big_number_slug=big_number_lot.slug,
            fractional_number_slug=fractional_number_lot.slug,
            empty_name_slug=empty_name_lot.slug,
            upper_slug=upper_slug_lot.slug,
            lot_b=lot_b.id,
            variant_b=variant_b.id,
        )
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant_a.id, tenant_b.id])))
            await session.commit()


async def test_category_repository_is_tenant_scoped(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCatalog,
) -> None:
    async with session_factory() as session:
        configure_session(session, tenant_id=seeded.tenant_a, database_role="keep_rollin_app")
        categories = await CategoryRepository(session).list_active()

    assert len(categories) == 1
    assert categories[0].name.value == "E-bikes"
    assert [item.code.value for item in categories[0].characteristics] == ["power"]


async def test_lot_repository_filters_and_price_from(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCatalog,
) -> None:
    async with session_factory() as session:
        configure_session(session, tenant_id=seeded.tenant_a, database_role="keep_rollin_app")
        repository = LotRepository(session)
        lots, total = await repository.list_active(
            filters=LotListFilters(query="Urban"),
            limit=10,
            offset=0,
        )
        detail = await repository.get_active_by_slug(Slug.create(seeded.active_slug))

    assert total == 1
    assert len(lots) == 1
    assert detail is not None
    assert detail.name.value == "Urban"
    price = detail.price_from()
    assert price is not None
    assert price.amount_minor == 40000
    assert price.at_units == 7
    assert price.battery_count == 1
    assert detail.is_bookable is True
    assert detail.currency == "RUB"


async def test_lot_repository_hides_archived_categories_and_other_tenants(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCatalog,
) -> None:
    async with session_factory() as session:
        configure_session(session, tenant_id=seeded.tenant_a, database_role="keep_rollin_app")
        repository = LotRepository(session)
        lots, total = await repository.list_active(
            filters=LotListFilters(),
            limit=10,
            offset=0,
        )
        archived = await repository.get_active_by_slug(Slug.create(seeded.archived_slug))
        archived_category = await repository.get_active_by_slug(
            Slug.create(seeded.archived_category_slug)
        )
        broken = await repository.get_active_by_slug(Slug.create(seeded.broken_slug))
        tierless = await repository.get_active_by_slug(Slug.create(seeded.tierless_slug))
        mismatched_battery = await repository.get_active_by_slug(
            Slug.create(seeded.mismatched_battery_slug)
        )
        empty_durations = await repository.get_active_by_slug(
            Slug.create(seeded.empty_durations_slug)
        )
        empty_battery_type = await repository.get_active_by_slug(
            Slug.create(seeded.empty_battery_type_slug)
        )
        bad_durations = await repository.get_active_by_slug(Slug.create(seeded.bad_durations_slug))
        growing_tiers = await repository.get_active_by_slug(Slug.create(seeded.growing_tiers_slug))
        malformed_json = await repository.get_active_by_slug(
            Slug.create(seeded.malformed_json_slug)
        )
        big_number = await repository.get_active_by_slug(Slug.create(seeded.big_number_slug))
        fractional_number = await repository.get_active_by_slug(
            Slug.create(seeded.fractional_number_slug)
        )
        empty_name = await repository.get_active_by_slug(Slug.create(seeded.empty_name_slug))

    assert total == 3
    assert {lot.name.value for lot in lots} == {"Urban", "Metro", "Draft"}
    assert archived is None
    assert archived_category is None
    assert broken is None
    assert tierless is None
    assert mismatched_battery is None
    assert empty_durations is None
    assert empty_battery_type is None
    assert bad_durations is None
    assert growing_tiers is None
    assert malformed_json is None
    assert big_number is None
    assert fractional_number is None
    assert empty_name is None


async def test_lot_repository_returns_same_slug_per_tenant_with_tenant_currency(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCatalog,
) -> None:
    async with session_factory() as session:
        configure_session(session, tenant_id=seeded.tenant_b, database_role="keep_rollin_app")
        detail = await LotRepository(session).get_active_by_slug(Slug.create(seeded.active_slug))

    assert detail is not None
    assert detail.name.value == "Urban B"
    assert detail.currency == "USD"


async def test_lot_repository_paginates_stably(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCatalog,
) -> None:
    seen: list[UUID] = []
    async with session_factory() as session:
        configure_session(session, tenant_id=seeded.tenant_a, database_role="keep_rollin_app")
        repository = LotRepository(session)
        for offset in (0, 1, 2):
            lots, total = await repository.list_active(
                filters=LotListFilters(),
                limit=1,
                offset=offset,
            )
            assert total == 3
            assert len(lots) == 1
            seen.append(lots[0].id)

    assert len(set(seen)) == 3
    assert seen == sorted(seen, reverse=True)


async def test_catalog_rejects_cross_tenant_parent_links(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: SeededCatalog,
) -> None:
    children = [
        (
            CharacteristicRecord(
                id=uuid4(),
                tenant_id=seeded.tenant_a,
                category_id=seeded.category_b,
                code=f"cross-{uuid4().hex[:8]}",
                name="Cross",
                type="text",
                unit=None,
                is_required=False,
                options=[],
                sort=1,
                is_archived=False,
            ),
            "fk_characteristic_tenant_category",
        ),
        (
            LotRecord(
                id=uuid4(),
                tenant_id=seeded.tenant_a,
                category_id=seeded.category_b,
                slug=f"cross-{uuid4().hex[:8]}",
                name="Cross",
                description=None,
                photos=[],
                characteristics={},
                rental_unit="day",
                battery_type=None,
                allowed_durations=[1],
                status="active",
                version=1,
            ),
            "fk_lot_tenant_category",
        ),
        (
            LotVariantRecord(
                id=uuid4(),
                tenant_id=seeded.tenant_a,
                lot_id=seeded.lot_b,
                battery_count=2,
                is_active=True,
            ),
            "fk_lot_variant_tenant_lot",
        ),
        (
            LotPriceTierRecord(
                id=uuid4(),
                tenant_id=seeded.tenant_a,
                variant_id=seeded.variant_b,
                min_units=2,
                price_per_unit_minor=1000,
            ),
            "fk_lot_price_tier_tenant_variant",
        ),
    ]

    for child, constraint in children:
        async with session_factory() as session:
            configure_session(session, tenant_id=seeded.tenant_a, database_role="keep_rollin_app")
            session.add(child)
            with pytest.raises(IntegrityError) as error:
                await session.flush()
            original = cast(Any, error.value.orig)
            assert original.sqlstate == "23503"
            assert constraint in str(original)
            await session.rollback()
