from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.repositories.i_admin_category_repository import (
    CharacteristicUpsert,
    IAdminCategoryRepository,
)
from src.domain.entities.category import (
    Category,
    CategoryNotFoundError,
    CategorySlugTakenError,
    CategoryVersionConflictError,
)
from src.domain.entities.characteristic import Characteristic, CharacteristicInUseError
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.slug import Slug
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.characteristic_record import CharacteristicRecord
from src.infrastructure.postgres.models.lot_record import LotRecord

UNIQUE_VIOLATION = "23505"


def _characteristic_to_domain(record: CharacteristicRecord) -> Characteristic:
    return Characteristic(
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        code=Slug.create(record.code),
        name=EntityName.create(record.name),
        type=record.type,  # type: ignore[arg-type]
        unit=record.unit,
        is_required=record.is_required,
        options=tuple(record.options),
        sort=record.sort,
        is_archived=record.is_archived,
    )


def _category_to_domain(record: CategoryRecord) -> Category:
    return Category(
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        name=EntityName.create(record.name),
        slug=Slug.create(record.slug),
        description=record.description,
        is_archived=record.is_archived,
        characteristics=tuple(_characteristic_to_domain(item) for item in record.characteristics),
        version=record.version,
    )


class AdminCategoryRepository(IAdminCategoryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        *,
        include_archived: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Category], int]:
        filters = [] if include_archived else [CategoryRecord.is_archived.is_(False)]
        total = await self._session.scalar(
            select(func.count()).select_from(CategoryRecord).where(*filters)
        )
        statement = (
            select(CategoryRecord)
            .where(*filters)
            .options(selectinload(CategoryRecord.characteristics))
            .order_by(CategoryRecord.name.asc(), CategoryRecord.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(statement)
        return [_category_to_domain(record) for record in result.scalars().all()], int(total or 0)

    async def create(
        self,
        *,
        name: str,
        slug: str,
        description: str | None,
    ) -> Category:
        record = CategoryRecord(
            tenant_id=self._tenant_id(),
            name=name,
            slug=slug,
            description=description,
            is_archived=False,
            version=1,
        )
        self._session.add(record)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION:
                raise CategorySlugTakenError("Category slug is already used") from exc
            raise
        created = await self._session.scalar(
            select(CategoryRecord)
            .where(CategoryRecord.id == record.id)
            .options(selectinload(CategoryRecord.characteristics))
            .execution_options(populate_existing=True)
        )
        if created is None:
            raise CategoryNotFoundError("Category not found after create")
        return _category_to_domain(created)

    async def update(
        self,
        category_id: UUID,
        *,
        version: int,
        changes: Mapping[str, object],
    ) -> Category:
        values: dict[str, object] = {
            **changes,
            "version": CategoryRecord.version + 1,
            "updated_at": func.now(),
        }
        try:
            result = await self._session.execute(
                update(CategoryRecord)
                .where(
                    CategoryRecord.id == category_id,
                    CategoryRecord.version == version,
                )
                .values(**values)
                .returning(CategoryRecord.id)
            )
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION:
                raise CategorySlugTakenError("Category slug is already used") from exc
            raise
        if result.scalar_one_or_none() is None:
            existing_version = await self._session.scalar(
                select(CategoryRecord.version).where(CategoryRecord.id == category_id)
            )
            if existing_version is None:
                raise CategoryNotFoundError("Category not found")
            raise CategoryVersionConflictError("Category version is stale")
        record = await self._session.scalar(
            select(CategoryRecord)
            .where(CategoryRecord.id == category_id)
            .options(selectinload(CategoryRecord.characteristics))
            .execution_options(populate_existing=True)
        )
        if record is None:
            raise CategoryNotFoundError("Category not found")
        return _category_to_domain(record)

    async def update_characteristics(
        self,
        category_id: UUID,
        *,
        version: int,
        definitions: Sequence[CharacteristicUpsert],
    ) -> Category:
        result = await self._session.execute(
            update(CategoryRecord)
            .where(
                CategoryRecord.id == category_id,
                CategoryRecord.version == version,
            )
            .values(
                version=CategoryRecord.version + 1,
                updated_at=func.now(),
            )
            .returning(CategoryRecord.id)
        )
        if result.scalar_one_or_none() is None:
            existing_version = await self._session.scalar(
                select(CategoryRecord.version).where(CategoryRecord.id == category_id)
            )
            if existing_version is None:
                raise CategoryNotFoundError("Category not found")
            raise CategoryVersionConflictError("Category version is stale")

        tenant_id = self._tenant_id()
        for definition in definitions:
            existing = await self._session.scalar(
                select(CharacteristicRecord).where(
                    CharacteristicRecord.category_id == category_id,
                    CharacteristicRecord.code == definition.code,
                )
            )
            if existing is not None:
                if existing.type != definition.type and await self._lot_has_value(
                    category_id,
                    definition.code,
                ):
                    raise CharacteristicInUseError(
                        "Characteristic type cannot change while lots use it"
                    )
                existing.name = definition.name
                existing.type = definition.type
                existing.unit = definition.unit
                existing.is_required = definition.is_required
                existing.options = list(definition.options)
                existing.sort = definition.sort
                existing.is_archived = definition.is_archived
            else:
                self._session.add(
                    CharacteristicRecord(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        category_id=category_id,
                        code=definition.code,
                        name=definition.name,
                        type=definition.type,
                        unit=definition.unit,
                        is_required=definition.is_required,
                        options=list(definition.options),
                        sort=definition.sort,
                        is_archived=definition.is_archived,
                    )
                )
        await self._session.flush()
        record = await self._session.scalar(
            select(CategoryRecord)
            .where(CategoryRecord.id == category_id)
            .options(selectinload(CategoryRecord.characteristics))
            .execution_options(populate_existing=True)
        )
        if record is None:
            raise CategoryNotFoundError("Category not found")
        return _category_to_domain(record)

    async def _lot_has_value(self, category_id: UUID, code: str) -> bool:
        value = await self._session.scalar(
            select(LotRecord.id)
            .where(
                LotRecord.category_id == category_id,
                LotRecord.characteristics.op("?")(code),
            )
            .limit(1)
        )
        return value is not None

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))
