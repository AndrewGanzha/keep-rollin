import re
import unicodedata
from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from uuid import UUID, uuid4

from sqlalchemy import DateTime, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models import Tenant
from src.application.dtos.admin_lot_dto import (
    MAX_LOT_NAME_LENGTH,
    MAX_LOT_SLUG_LENGTH,
    CharacteristicsInput,
    CreateLotRequest,
    LotPhotoInput,
    LotVariantInput,
    ManualLotStatus,
    UpdateLotRequest,
)
from src.domain.entities.lot import Lot, LotStatus
from src.domain.entities.tenant_profile import TenantPolicies
from src.domain.exceptions import LotHasActiveRentalError, LotUnavailableError
from src.domain.value_objects.price import PriceTier
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.tenant_settings_record import TenantSettingsRecord
from src.infrastructure.postgres.repositories.file_repository import FileRepository
from src.infrastructure.postgres.repositories.lot_repository import LotRepository
from src.infrastructure.postgres.repositories.occupancy_repository import insert_occupancy


class AdminLotNotFoundError(Exception):
    pass


class AdminLotVersionConflictError(Exception):
    pass


class AdminLotSlugTakenError(Exception):
    pass


class InvalidLotFieldsError(Exception):
    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__("Invalid lot fields")
        self.fields = fields


_RUSSIAN_ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
_CYRILLIC = str.maketrans(
    dict(
        zip(
            _RUSSIAN_ALPHABET,
            (
                "a",
                "b",
                "v",
                "g",
                "d",
                "e",
                "e",
                "zh",
                "z",
                "i",
                "y",
                "k",
                "l",
                "m",
                "n",
                "o",
                "p",
                "r",
                "s",
                "t",
                "u",
                "f",
                "h",
                "c",
                "ch",
                "sh",
                "sch",
                "",
                "y",
                "",
                "e",
                "yu",
                "ya",
            ),
            strict=True,
        )
    )
)


def _slug_stem(name: str) -> str:
    ascii_name = (
        unicodedata.normalize("NFKD", name.lower().translate(_CYRILLIC))
        .encode("ascii", "ignore")
        .decode()
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_name)


def _generated_slug(name: str, lot_id: UUID) -> str:
    prefix = _slug_stem(name)[:47].strip("-")
    return f"{prefix or 'lot'}-{lot_id.hex}"


def _characteristic_values(
    category: CategoryRecord,
    requested: CharacteristicsInput,
    previous: CharacteristicsInput,
) -> CharacteristicsInput:
    definitions = {entry.code: entry for entry in category.characteristics}
    values = {
        code: value
        for code, value in previous.items()
        if code in definitions and definitions[code].is_archived
    }
    errors: dict[str, str] = {}
    for code, value in requested.items():
        field = f"characteristics.{code}"
        definition = definitions.get(code)
        if definition is None:
            errors[field] = "unknown characteristic"
        elif definition.is_archived:
            if code not in values or values[code] != value:
                errors[field] = "archived characteristic cannot be set or changed"
        elif definition.type == "number" and not isinstance(value, (int, float)):
            errors[field] = "must be a number"
        elif definition.type == "text" and not isinstance(value, str):
            errors[field] = "must be a string"
        elif definition.type == "select" and value not in definition.options:
            errors[field] = "must be a defined option"
        else:
            values[code] = value

    for code, definition in definitions.items():
        if definition.is_required and not definition.is_archived:
            current_value = values.get(code)
            if current_value is None or (
                isinstance(current_value, str) and not current_value.strip()
            ):
                errors.setdefault(f"characteristics.{code}", "required characteristic")

    if errors:
        raise InvalidLotFieldsError(errors)
    return values


def _validate_configuration(
    durations: list[int],
    variants: Sequence[LotVariantInput | LotVariantRecord],
    battery_type: str | None,
) -> None:
    errors: dict[str, str] = {}
    for index, (previous, current) in enumerate(pairwise(durations), 1):
        if current <= previous:
            errors[f"allowed_durations.{index}"] = "durations must be unique and increasing"

    if not durations:
        errors["allowed_durations"] = "at least one duration is required"
    if not variants:
        errors["variants"] = "at least one variant is required"

    counts: set[int] = set()
    for index, variant in enumerate(variants):
        prefix = f"variants.{index}"
        if variant.battery_count in counts:
            errors[f"{prefix}.battery_count"] = "battery counts must be unique"
        counts.add(variant.battery_count)

        if variant.battery_count > 0 and not (battery_type and battery_type.strip()):
            errors["battery_type"] = "required for variants with batteries"

        tiers: Sequence[PriceTier | LotPriceTierRecord] = variant.price_tiers
        if isinstance(variant, LotVariantRecord):
            tiers = sorted(tiers, key=lambda tier: tier.min_units)
        if not tiers:
            errors[f"{prefix}.price_tiers"] = "at least one price tier is required"
            continue
        if durations and tiers[0].min_units != durations[0]:
            errors[f"{prefix}.price_tiers.0.min_units"] = "must match the minimum allowed duration"
        for tier_index, (earlier, later) in enumerate(pairwise(tiers), 1):
            field = f"{prefix}.price_tiers.{tier_index}"
            if later.min_units <= earlier.min_units:
                errors[f"{field}.min_units"] = "tier durations must be unique and increasing"
            if later.price_per_unit_minor > earlier.price_per_unit_minor:
                errors[f"{field}.price_per_unit_minor"] = "price per unit must not increase"

    if errors:
        raise InvalidLotFieldsError(errors)


class AdminLotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    async def list_page(
        self,
        *,
        category_id: UUID | None,
        status: LotStatus | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Lot], int]:
        filters: list[ColumnElement[bool]] = [LotRecord.tenant_id == self._tenant_id]
        if category_id is not None:
            filters.append(LotRecord.category_id == category_id)
        if status is not None:
            filters.append(LotRecord.status == status)
        if query:
            # Match Russian names even on PostgreSQL clusters with the C locale.
            name = func.translate(LotRecord.name, _RUSSIAN_ALPHABET.upper(), _RUSSIAN_ALPHABET)
            filters.append(
                or_(
                    name.icontains(query.lower(), autoescape=True),
                    LotRecord.slug.icontains(query, autoescape=True),
                )
            )

        total = await self._session.scalar(
            select(func.count()).select_from(LotRecord).where(*filters)
        )
        result = await self._session.execute(
            select(LotRecord)
            .where(*filters)
            .options(joinedload(LotRecord.variants).joinedload(LotVariantRecord.price_tiers))
            .order_by(LotRecord.name, LotRecord.id)
            .limit(limit)
            .offset(offset)
        )
        currency = await self._currency()
        lots = [LotRepository._to_domain(row, currency) for row in result.unique().scalars()]
        return lots, int(total or 0)

    async def get(self, lot_id: UUID) -> Lot:
        return LotRepository._to_domain(await self._get_record(lot_id), await self._currency())

    async def create(self, payload: CreateLotRequest) -> Lot:
        category = await self._locked_category(payload.category_id)
        if category.is_archived:
            raise InvalidLotFieldsError({"category_id": "category is archived"})
        characteristics = _characteristic_values(category, payload.characteristics, {})
        _validate_configuration(payload.allowed_durations, payload.variants, payload.battery_type)

        lot_id = uuid4()
        record = LotRecord(
            id=lot_id,
            tenant_id=self._tenant_id,
            category_id=payload.category_id,
            name=payload.name,
            slug=payload.slug or _generated_slug(payload.name, lot_id),
            description=payload.description,
            characteristics=characteristics,
            rental_unit=payload.rental_unit,
            battery_type=payload.battery_type,
            allowed_durations=payload.allowed_durations,
            status=payload.status,
            variants=[],
        )
        self._replace_variants(record, payload.variants)
        self._session.add(record)
        await self._flush_lot()
        await self._set_photos(record, payload)
        return await self.get(lot_id)

    async def create_bulk(self, template: CreateLotRequest, count: int) -> list[Lot]:
        slug_stem = template.slug or _slug_stem(template.name).strip("-") or "lot"
        lots = []
        for number in range(1, count + 1):
            name_suffix = f" №{number}"
            slug_suffix = f"-{number}"
            name = template.name[: MAX_LOT_NAME_LENGTH - len(name_suffix)].rstrip()
            slug = slug_stem[: MAX_LOT_SLUG_LENGTH - len(slug_suffix)].rstrip("-") or "lot"
            payload = template.model_copy(
                update={"name": f"{name}{name_suffix}", "slug": f"{slug}{slug_suffix}"}
            )
            lots.append(await self.create(payload))
        return lots

    async def update(self, lot_id: UUID, payload: UpdateLotRequest) -> Lot:
        record = await self._get_record(lot_id, lock=True)
        if record.version != payload.version:
            raise AdminLotVersionConflictError
        if payload.status is not None and payload.status != record.status:
            raise InvalidLotFieldsError({"status": "lot status cannot be changed here"})

        present = payload.model_fields_set
        if present & {"variants", "allowed_durations", "battery_type"}:
            _validate_configuration(
                payload.allowed_durations or record.allowed_durations,
                payload.variants
                or sorted(record.variants, key=lambda variant: variant.battery_count),
                payload.battery_type if "battery_type" in present else record.battery_type,
            )

        category_id = payload.category_id or record.category_id
        category_changed = category_id != record.category_id
        if category_changed or payload.characteristics is not None:
            category = await self._locked_category(category_id)
            if category_changed and category.is_archived:
                raise InvalidLotFieldsError({"category_id": "category is archived"})
            record.characteristics = _characteristic_values(
                category,
                record.characteristics
                if payload.characteristics is None
                else payload.characteristics,
                {} if category_changed else record.characteristics,
            )

        for field in (
            "category_id",
            "name",
            "slug",
            "description",
            "rental_unit",
            "battery_type",
            "allowed_durations",
        ):
            if field in present:
                setattr(record, field, getattr(payload, field))
        if payload.variants is not None:
            self._replace_variants(record, payload.variants)
        record.version += 1
        await self._flush_lot()
        await self._set_photos(record, payload)
        return await self.get(lot_id)

    async def set_status(
        self, lot_id: UUID, status: ManualLotStatus, *, actor_id: UUID
    ) -> tuple[Lot, str | None]:
        record = await self._get_record(lot_id, lock=True)
        old_status = record.status
        if old_status == status:
            return LotRepository._to_domain(record, await self._currency()), None

        if status == "archived" or (status == "maintenance" and old_status != "overdue"):
            has_active_booking = await self._session.scalar(
                select(
                    exists().where(
                        OccupancyRecord.tenant_id == self._tenant_id,
                        OccupancyRecord.lot_id == lot_id,
                        OccupancyRecord.kind == "booking",
                        OccupancyRecord.status == "active",
                    )
                )
            )
            if has_active_booking:
                raise LotHasActiveRentalError
        if old_status == "overdue":
            raise LotUnavailableError

        # Read wall-clock time after acquiring the lot lock.
        now = (
            await self._session.execute(select(func.clock_timestamp(type_=DateTime(timezone=True))))
        ).scalar_one()
        if status == "maintenance":
            await insert_occupancy(
                self._session,
                OccupancyRecord(
                    tenant_id=self._tenant_id,
                    lot_id=lot_id,
                    kind="maintenance",
                    ref_id=lot_id,
                    status="active",
                    period=Range(now, None, bounds="[)"),
                    created_by=actor_id,
                    created_at=now,
                    updated_at=now,
                ),
            )
        elif old_status == "maintenance":
            await self._close_status_maintenance(lot_id, now)

        record.status = status
        record.version += 1
        record.updated_at = now
        await self._session.flush()
        return LotRepository._to_domain(record, await self._currency()), old_status

    async def _close_status_maintenance(self, lot_id: UUID, now: datetime) -> None:
        start = func.lower(OccupancyRecord.period)
        await self._session.execute(
            update(OccupancyRecord)
            .where(
                OccupancyRecord.tenant_id == self._tenant_id,
                OccupancyRecord.lot_id == lot_id,
                OccupancyRecord.ref_id == lot_id,
                OccupancyRecord.kind == "maintenance",
                OccupancyRecord.status == "active",
                or_(
                    func.upper_inf(OccupancyRecord.period), func.upper(OccupancyRecord.period) > now
                ),
            )
            .values(
                status="released",
                period=func.tstzrange(start, func.greatest(start, now), "[)"),
                updated_at=now,
            )
        )

    async def _get_record(self, lot_id: UUID, *, lock: bool = False) -> LotRecord:
        statement = (
            select(LotRecord)
            .where(LotRecord.id == lot_id, LotRecord.tenant_id == self._tenant_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            # Fetch the children after the lot lock has been acquired.
            statement = statement.with_for_update().options(
                selectinload(LotRecord.variants).selectinload(LotVariantRecord.price_tiers)
            )
        else:
            statement = statement.options(
                joinedload(LotRecord.variants).joinedload(LotVariantRecord.price_tiers)
            )
        result = await self._session.execute(statement)
        record = result.unique().scalar_one_or_none()
        if record is None:
            raise AdminLotNotFoundError
        return record

    async def _locked_category(self, category_id: UUID) -> CategoryRecord:
        category = await self._session.scalar(
            select(CategoryRecord)
            .where(CategoryRecord.id == category_id, CategoryRecord.tenant_id == self._tenant_id)
            .options(selectinload(CategoryRecord.characteristics))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if category is None:
            raise AdminLotNotFoundError
        return category

    async def _currency(self) -> str:
        currency = await self._session.scalar(
            select(Tenant.currency).where(Tenant.id == self._tenant_id)
        )
        if currency is None:
            raise RuntimeError("tenant currency is unavailable")
        return currency

    async def _flush_lot(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            cause = getattr(exc.orig, "__cause__", None)
            if getattr(cause, "constraint_name", None) == "uq_lot_tenant_slug":
                raise AdminLotSlugTakenError from exc
            raise

    def _replace_variants(self, record: LotRecord, requested: list[LotVariantInput]) -> None:
        current = {variant.battery_count: variant for variant in record.variants}
        variants = []
        for item in requested:
            variant = current.get(item.battery_count)
            if variant is None:
                variant = LotVariantRecord(
                    id=uuid4(),
                    tenant_id=self._tenant_id,
                    lot_id=record.id,
                    battery_count=item.battery_count,
                    is_active=item.is_active,
                    price_tiers=[],
                )
            elif "is_active" in item.model_fields_set:
                variant.is_active = item.is_active

            tiers = {tier.min_units: tier for tier in variant.price_tiers}
            variant.price_tiers = [
                tiers.get(price.min_units)
                or LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=self._tenant_id,
                    variant_id=variant.id,
                    min_units=price.min_units,
                )
                for price in item.price_tiers
            ]
            for tier, price in zip(variant.price_tiers, item.price_tiers, strict=True):
                tier.price_per_unit_minor = price.price_per_unit_minor
            variants.append(variant)
        record.variants = variants

    async def _set_photos(self, record: LotRecord, payload: LotPhotoInput) -> None:
        if payload.photos is None and payload.file_ids is None:
            return
        if payload.photos is not None and payload.file_ids is not None:
            raise InvalidLotFieldsError({"file_ids": "provide either file_ids or photos"})
        policies = await self._session.scalar(
            select(TenantSettingsRecord.policies).where(
                TenantSettingsRecord.tenant_id == self._tenant_id
            )
        )
        limit = TenantPolicies.from_mapping(policies or {}).lot_photos_max
        field = "file_ids" if payload.file_ids is not None else "photos"
        if len(payload.file_ids or payload.photos or []) > limit:
            raise InvalidLotFieldsError({field: f"at most {limit} photos are allowed"})
        if payload.file_ids is not None:
            seen: set[UUID] = set()
            for index, file_id in enumerate(payload.file_ids):
                if file_id in seen:
                    raise InvalidLotFieldsError({f"file_ids.{index}": "file IDs must be unique"})
                seen.add(file_id)

        record.photos = await FileRepository(self._session).set_lot_photos(
            lot_id=record.id,
            file_ids=payload.file_ids,
            legacy_urls=payload.photos,
        )
        await self._session.flush()
