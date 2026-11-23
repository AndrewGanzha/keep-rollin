from typing import cast
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models import Tenant
from src.application.repositories.i_lot_repository import ILotRepository, LotListFilters
from src.domain.entities.lot import Lot
from src.domain.entities.lot_variant import LotVariant
from src.domain.value_objects.battery_count import BatteryCount
from src.domain.value_objects.duration import AllowedDurations
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.price import PriceTier
from src.domain.value_objects.slug import Slug
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord


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
        where_clauses = [
            LotRecord.status == "active",
            CategoryRecord.is_archived.is_(False),
            Tenant.currency.op("~")("^[A-Z]{3}$"),
            self._structurally_valid_lot(),
        ]
        if filters.category_id is not None:
            where_clauses.append(LotRecord.category_id == filters.category_id)
        if filters.query:
            pattern = f"%{filters.query}%"
            where_clauses.append(or_(LotRecord.name.ilike(pattern), LotRecord.slug.ilike(pattern)))

        total = await self._session.scalar(
            select(func.count(LotRecord.id))
            .join(CategoryRecord, CategoryRecord.id == LotRecord.category_id)
            .join(Tenant, Tenant.id == LotRecord.tenant_id)
            .where(*where_clauses)
        )
        statement = (
            select(LotRecord)
            .join(CategoryRecord, CategoryRecord.id == LotRecord.category_id)
            .join(Tenant, Tenant.id == LotRecord.tenant_id)
            .where(*where_clauses)
            .options(selectinload(LotRecord.variants).selectinload(LotVariantRecord.price_tiers))
            .order_by(LotRecord.created_at.desc(), LotRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        records = result.scalars().all()
        currency = await self._tenant_currency(records[0].tenant_id) if records else "RUB"
        return [self._to_domain(record, currency) for record in records], total or 0

    async def get_active_by_slug(self, slug: Slug) -> Lot | None:
        statement = (
            select(LotRecord)
            .join(CategoryRecord, CategoryRecord.id == LotRecord.category_id)
            .join(Tenant, Tenant.id == LotRecord.tenant_id)
            .where(
                LotRecord.slug == slug.value,
                LotRecord.status == "active",
                CategoryRecord.is_archived.is_(False),
                Tenant.currency.op("~")("^[A-Z]{3}$"),
                self._structurally_valid_lot(),
            )
            .options(selectinload(LotRecord.variants).selectinload(LotVariantRecord.price_tiers))
        )
        result = await self._session.execute(statement)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record, await self._tenant_currency(record.tenant_id))

    @staticmethod
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
            (
                "lot.allowed_durations = "
                "ARRAY(SELECT DISTINCT unnest(lot.allowed_durations) ORDER BY 1)"
            ),
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
