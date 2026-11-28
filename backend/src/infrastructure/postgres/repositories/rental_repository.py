from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from sqlalchemy.sql.elements import ColumnElement

from app.models import User
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord, RentalStatus

type RentalDetails = tuple[RentalRecord, LotRecord, User]


class RentalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    async def add(self, record: RentalRecord) -> RentalRecord:
        if record.tenant_id != self._tenant_id:
            raise ValueError("rental tenant does not match the session")
        self._session.add(record)
        await self.flush()
        return record

    async def flush(self) -> None:
        await self._session.flush()

    async def lock_lot(self, lot_id: UUID) -> LotRecord | None:
        return await self._session.scalar(
            select(LotRecord)
            .where(LotRecord.tenant_id == self._tenant_id, LotRecord.id == lot_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def lock(self, rental_id: UUID, *, user_id: UUID | None = None) -> RentalRecord | None:
        filters = self._detail_filters(rental_id, user_id)
        lot_id = await self._session.scalar(select(RentalRecord.lot_id).where(*filters))
        if lot_id is None or await self.lock_lot(lot_id) is None:
            return None
        # Booking and lot status changes take the lot lock before writing occupancy.
        return await self._session.scalar(
            select(RentalRecord)
            .where(*filters, RentalRecord.lot_id == lot_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def get_details(
        self, rental_id: UUID, *, user_id: UUID | None = None
    ) -> RentalDetails | None:
        result = await self._session.execute(
            self._with_details().where(*self._detail_filters(rental_id, user_id))
        )
        row = result.one_or_none()
        if row is None:
            return None
        rental, lot, user = row
        return rental, lot, user

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        status: RentalStatus | None = None,
        user_id: UUID | None = None,
        lot_id: UUID | None = None,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> tuple[list[RentalDetails], int]:
        filters: list[ColumnElement[bool]] = [RentalRecord.tenant_id == self._tenant_id]
        if status is not None:
            filters.append(RentalRecord.status == status)
        if user_id is not None:
            filters.append(RentalRecord.user_id == user_id)
        if lot_id is not None:
            filters.append(RentalRecord.lot_id == lot_id)
        if period_from is not None:
            filters.append(RentalRecord.end_time > period_from)
        if period_to is not None:
            filters.append(RentalRecord.start_time < period_to)
        result = await self._session.execute(
            self._with_details()
            .where(*filters)
            .order_by(RentalRecord.created_at.desc(), RentalRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(RentalRecord).where(*filters)
        )
        return [(rental, lot, user) for rental, lot, user in result], int(total or 0)

    def _detail_filters(self, rental_id: UUID, user_id: UUID | None) -> list[ColumnElement[bool]]:
        filters = [RentalRecord.tenant_id == self._tenant_id, RentalRecord.id == rental_id]
        if user_id is not None:
            filters.append(RentalRecord.user_id == user_id)
        return filters

    @staticmethod
    def _with_details() -> Select[RentalRecord, LotRecord, User]:
        return (
            select(RentalRecord, LotRecord, User)
            .join(
                LotRecord,
                and_(
                    LotRecord.tenant_id == RentalRecord.tenant_id,
                    LotRecord.id == RentalRecord.lot_id,
                ),
            )
            .join(
                User,
                and_(User.tenant_id == RentalRecord.tenant_id, User.id == RentalRecord.user_id),
            )
            .options(load_only(User.id, User.name, User.email))
        )
