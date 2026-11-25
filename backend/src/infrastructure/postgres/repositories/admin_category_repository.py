from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.repositories.i_admin_category_repository import IAdminCategoryRepository
from src.domain.entities.category import (
    Category,
    CategoryNotFoundError,
    CategorySlugTakenError,
    CategoryVersionConflictError,
)
from src.domain.entities.characteristic import Characteristic
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.slug import Slug
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.characteristic_record import CharacteristicRecord

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
        characteristics=tuple(
            _characteristic_to_domain(item)
            for item in record.characteristics
            if not item.is_archived
        ),
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

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))
