import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, Text, and_, exists, func, literal, or_, select, text, true
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import JSONB, Range
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models import Tenant
from src.application.repositories.i_lot_repository import (
    ILotRepository,
    InvalidLotCharacteristicFilter,
    LotListFilters,
)
from src.domain.entities.lot import Lot
from src.domain.entities.lot_variant import LotVariant
from src.domain.value_objects.battery_count import BatteryCount
from src.domain.value_objects.duration import AllowedDurations
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.price import PriceTier
from src.domain.value_objects.slug import Slug
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.characteristic_record import CharacteristicRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord

_DECIMAL_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_MAX_CATALOG_NUMBER = Decimal("1e308")


def public_lot_query() -> Select[LotRecord]:
    return (
        select(LotRecord)
        .join(CategoryRecord, CategoryRecord.id == LotRecord.category_id)
        .join(Tenant, Tenant.id == LotRecord.tenant_id)
        .where(
            LotRecord.status == "active",
            CategoryRecord.is_archived.is_(False),
            Tenant.currency.op("~")("^[A-Z]{3}$"),
            _structurally_valid_lot(),
        )
    )


def bookable_lot() -> ColumnElement[bool]:
    return exists().where(
        LotVariantRecord.lot_id == LotRecord.id,
        LotVariantRecord.is_active.is_(True),
    )


def _numeric_filter_value(value: str) -> str | None:
    if _DECIMAL_NUMBER.fullmatch(value) is None:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    exponent = number.as_tuple().exponent
    # Match the public lot number range and PostgreSQL's maximum numeric scale.
    if not isinstance(exponent, int) or exponent < -16383:
        return None
    if number.copy_abs() > _MAX_CATALOG_NUMBER:
        return None
    return str(number) if number else "0"


def _structurally_valid_lot() -> ColumnElement[bool]:
    has_variants = exists().where(LotVariantRecord.lot_id == LotRecord.id)
    has_empty_variant = exists().where(
        LotVariantRecord.lot_id == LotRecord.id,
        ~exists().where(LotPriceTierRecord.variant_id == LotVariantRecord.id),
    )
    has_positive_battery = exists().where(
        LotVariantRecord.lot_id == LotRecord.id,
        LotVariantRecord.battery_count > 0,
    )
    battery_type_ok = ~has_positive_battery | (
        LotRecord.battery_type.is_not(None) & (LotRecord.battery_type != "")
    )
    domain_predicates = [
        "lot.name <> ''",
        "length(lot.name) <= 120",
        "lot.slug::text ~ '^[a-z0-9-]+$'",
        "length(lot.slug::text) <= 80",
        "jsonb_typeof(lot.photos) = 'array'",
        "jsonb_typeof(lot.characteristics) = 'object'",
        "array_length(lot.allowed_durations, 1) >= 1",
        "array_lower(lot.allowed_durations, 1) = 1",
        ("lot.allowed_durations = ARRAY(SELECT DISTINCT unnest(lot.allowed_durations) ORDER BY 1)"),
        "lot.allowed_durations <@ ARRAY(SELECT generate_series(1, 365))",
        "lot.version > 0",
        (
            "NOT EXISTS (SELECT 1 FROM lot_variant v WHERE v.lot_id = lot.id "
            "AND (SELECT MIN(t.min_units) FROM lot_price_tier t "
            "WHERE t.variant_id = v.id) IS DISTINCT FROM "
            "lot.allowed_durations[array_lower(lot.allowed_durations, 1)])"
        ),
        (
            "NOT EXISTS (SELECT 1 FROM lot_variant v "
            "JOIN lot_price_tier a ON a.variant_id = v.id "
            "JOIN lot_price_tier b ON b.variant_id = v.id AND a.min_units < b.min_units "
            "WHERE v.lot_id = lot.id "
            "AND a.price_per_unit_minor < b.price_per_unit_minor)"
        ),
        (
            "NOT EXISTS (SELECT 1 FROM jsonb_each(CASE "
            "WHEN jsonb_typeof(lot.characteristics) = 'object' "
            "THEN lot.characteristics ELSE '{}'::jsonb END) AS kv "
            "WHERE jsonb_typeof(kv.value) NOT IN ('string', 'number'))"
        ),
        (
            "NOT EXISTS (SELECT 1 FROM jsonb_each(CASE "
            "WHEN jsonb_typeof(lot.characteristics) = 'object' "
            "THEN lot.characteristics ELSE '{}'::jsonb END) AS kv "
            "WHERE jsonb_typeof(kv.value) = 'number' "
            "AND (kv.value::text ~* '(nan|infinity)' "
            "OR length(kv.value::text) > 4000 "
            "OR kv.value::numeric > 1e308 "
            "OR kv.value::numeric < -1e308))"
        ),
        (
            "NOT EXISTS (SELECT 1 FROM jsonb_array_elements(CASE "
            "WHEN jsonb_typeof(lot.photos) = 'array' "
            "THEN lot.photos ELSE '[]'::jsonb END) AS p "
            "WHERE jsonb_typeof(p) <> 'string')"
        ),
    ]
    return and_(
        has_variants,
        ~has_empty_variant,
        battery_type_ok,
        *(cast(ColumnElement[bool], text(predicate)) for predicate in domain_predicates),
    )


class LotRepository(ILotRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(
        self,
        *,
        filters: LotListFilters,
        limit: int,
        offset: int,
    ) -> tuple[list[Lot], int]:
        statement = public_lot_query()
        if filters.category_id is not None:
            statement = statement.where(LotRecord.category_id == filters.category_id)
        if filters.query:
            pattern = f"%{filters.query}%"
            statement = statement.where(
                or_(LotRecord.name.ilike(pattern), LotRecord.slug.ilike(pattern))
            )
        if filters.characteristics:
            statement = statement.where(*await self._characteristic_predicates(filters))
        if filters.available_period is not None:
            period = filters.available_period
            interval = Range(period.start, period.end, bounds="[)")
            occupied = exists().where(
                OccupancyRecord.tenant_id == LotRecord.tenant_id,
                OccupancyRecord.lot_id == LotRecord.id,
                OccupancyRecord.status == "active",
                OccupancyRecord.period.overlaps(interval),
            )
            statement = statement.where(bookable_lot(), ~occupied)
        eligible = statement.with_only_columns(LotRecord.id, maintain_column_froms=True).cte()
        totals = select(func.count().label("total")).select_from(eligible).subquery()
        order: list[ColumnElement[Any]] = [LotRecord.created_at.desc(), LotRecord.id.desc()]
        if filters.sort == "name_asc":
            order.insert(0, LotRecord.name.asc())
        elif filters.sort in ("price_asc", "price_desc"):
            price = (
                select(func.min(LotPriceTierRecord.price_per_unit_minor))
                .join(LotVariantRecord, LotVariantRecord.id == LotPriceTierRecord.variant_id)
                .where(
                    LotVariantRecord.lot_id == LotRecord.id,
                    LotVariantRecord.is_active.is_(True),
                )
                .scalar_subquery()
            )
            direction = price.asc() if filters.sort == "price_asc" else price.desc()
            order.insert(0, direction.nulls_last())
        page = (
            select(LotRecord, func.row_number().over(order_by=order).label("position"))
            .join(eligible, eligible.c.id == LotRecord.id)
            .order_by(*order)
            .offset(offset)
            .limit(limit)
            .subquery()
        )
        paged_lot = aliased(LotRecord, page)
        # One filtered snapshot for both rows and total, including an empty page.
        result = await self._session.execute(
            select(paged_lot, totals.c.total, Tenant.currency)
            .select_from(totals)
            .outerjoin(page, true())
            .outerjoin(Tenant, Tenant.id == paged_lot.tenant_id)
            .options(selectinload(paged_lot.variants).selectinload(LotVariantRecord.price_tiers))
            .order_by(page.c.position)
        )
        rows = result.all()
        return [
            self._to_domain(record, currency) for record, _, currency in rows if record is not None
        ], int(rows[0].total)

    async def _characteristic_predicates(
        self,
        filters: LotListFilters,
    ) -> list[ColumnElement[bool]]:
        statement = (
            select(CharacteristicRecord)
            .join(CategoryRecord, CategoryRecord.id == CharacteristicRecord.category_id)
            .where(
                sql_cast(CharacteristicRecord.code, Text).in_(
                    [code for code, _ in filters.characteristics]
                ),
                CharacteristicRecord.is_archived.is_(False),
                CategoryRecord.is_archived.is_(False),
            )
        )
        if filters.category_id is not None:
            statement = statement.where(CategoryRecord.id == filters.category_id)
        definitions: dict[str, list[CharacteristicRecord]] = defaultdict(list)
        for definition in await self._session.scalars(statement):
            definitions[definition.code].append(definition)

        predicates = []
        for code, raw_value in filters.characteristics:
            if code not in definitions:
                raise InvalidLotCharacteristicFilter(code, "unknown characteristic")
            number = _numeric_filter_value(raw_value)
            string = json.dumps(raw_value, ensure_ascii=False)
            compatible_categories: dict[str, list[UUID]] = defaultdict(list)
            for definition in definitions[code]:
                if definition.type == "number" and number is not None:
                    compatible_categories[number].append(definition.category_id)
                elif definition.type == "text" or (
                    definition.type == "select" and raw_value in definition.options
                ):
                    compatible_categories[string].append(definition.category_id)
            if not compatible_categories:
                raise InvalidLotCharacteristicFilter(code, "invalid characteristic value")
            predicates.append(
                or_(
                    *(
                        and_(
                            LotRecord.category_id.in_(category_ids),
                            LotRecord.characteristics.contains(
                                sql_cast(
                                    literal(f"{{{json.dumps(code)}:{value}}}"),
                                    JSONB,
                                )
                            ),
                        )
                        for value, category_ids in compatible_categories.items()
                    )
                )
            )
        return predicates

    async def get_active_by_slug(self, slug: Slug) -> Lot | None:
        statement = (
            public_lot_query()
            .where(LotRecord.slug == slug.value)
            .options(selectinload(LotRecord.variants).selectinload(LotVariantRecord.price_tiers))
        )
        result = await self._session.execute(statement)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record, await self._tenant_currency(record.tenant_id))

    async def _tenant_currency(self, tenant_id: UUID) -> str:
        currency = await self._session.scalar(select(Tenant.currency).where(Tenant.id == tenant_id))
        if currency is None:
            raise RuntimeError("tenant currency is unavailable")
        return str(currency)

    @staticmethod
    def _to_domain(record: LotRecord, currency: str) -> Lot:
        return Lot(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            slug=Slug.create(record.slug),
            name=EntityName.create(record.name),
            description=record.description,
            category_id=record.category_id,
            photos=tuple(record.photos),
            characteristics=record.characteristics,
            rental_unit=record.rental_unit,  # type: ignore[arg-type]
            battery_type=record.battery_type,
            variants=tuple(
                LotRepository._variant_to_domain(variant)
                for variant in sorted(record.variants, key=lambda item: item.battery_count)
            ),
            allowed_durations=AllowedDurations.create(list(record.allowed_durations)),
            status=record.status,  # type: ignore[arg-type]
            version=record.version,
            currency=currency,
        )

    @staticmethod
    def _variant_to_domain(record: LotVariantRecord) -> LotVariant:
        return LotVariant(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            battery_count=BatteryCount.create(record.battery_count),
            is_active=record.is_active,
            price_tiers=tuple(
                LotRepository._tier_to_domain(tier)
                for tier in sorted(record.price_tiers, key=lambda item: item.min_units)
            ),
        )

    @staticmethod
    def _tier_to_domain(record: LotPriceTierRecord) -> PriceTier:
        return PriceTier.create(record.min_units, record.price_per_unit_minor)
