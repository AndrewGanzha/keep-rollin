from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.repositories.i_category_repository import ICategoryRepository
from src.domain.entities.category import Category
from src.domain.entities.characteristic import Characteristic
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.slug import Slug
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.characteristic_record import CharacteristicRecord


class CategoryRepository(ICategoryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self) -> list[Category]:
        statement = (
            select(CategoryRecord)
            .where(CategoryRecord.is_archived.is_(False))
            .options(selectinload(CategoryRecord.characteristics))
            .order_by(CategoryRecord.name.asc(), CategoryRecord.id.asc())
        )
        result = await self._session.execute(statement)
        return [self._to_domain(record) for record in result.scalars().all()]

    @staticmethod
    def _to_domain(record: CategoryRecord) -> Category:
        return Category(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            name=EntityName.create(record.name),
            slug=Slug.create(record.slug),
            description=record.description,
            is_archived=record.is_archived,
            characteristics=tuple(
                CategoryRepository._characteristic_to_domain(item)
                for item in record.characteristics
                if not item.is_archived
            ),
        )

    @staticmethod
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
