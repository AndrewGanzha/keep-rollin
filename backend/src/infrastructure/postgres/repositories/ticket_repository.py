from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from sqlalchemy.sql.elements import ColumnElement

from app.models import User
from src.infrastructure.postgres.models.file_record import FileRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.models.ticket_record import (
    TicketAttachmentRecord,
    TicketRecord,
    TicketStatus,
)

type TicketDetails = tuple[TicketRecord, LotRecord, User]


class TicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    async def add(self, record: TicketRecord, *, file_ids: Sequence[UUID] = ()) -> TicketRecord:
        """Store the ticket and photo IDs locked by lock_photo_ids in the same transaction."""
        if record.tenant_id != self._tenant_id:
            raise ValueError("ticket tenant does not match the session")
        self._session.add(record)
        await self.flush()
        if file_ids:
            self._session.add_all(
                TicketAttachmentRecord(
                    tenant_id=self._tenant_id,
                    ticket_id=record.id,
                    file_id=file_id,
                    position=position,
                )
                for position, file_id in enumerate(file_ids)
            )
            await self.flush()
        return record

    async def flush(self) -> None:
        await self._session.flush()

    async def lock(self, ticket_id: UUID) -> TicketRecord | None:
        return await self._session.scalar(
            select(TicketRecord)
            .where(TicketRecord.tenant_id == self._tenant_id, TicketRecord.id == ticket_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def get_details(
        self, ticket_id: UUID, *, user_id: UUID | None = None
    ) -> TicketDetails | None:
        filters = [TicketRecord.tenant_id == self._tenant_id, TicketRecord.id == ticket_id]
        if user_id is not None:
            filters.append(RentalRecord.user_id == user_id)
        result = await self._session.execute(self._with_details().where(*filters))
        row = result.one_or_none()
        if row is None:
            return None
        ticket, lot, user = row
        return ticket, lot, user

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        status: TicketStatus | None = None,
        user_id: UUID | None = None,
        lot_id: UUID | None = None,
        rental_id: UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> tuple[list[TicketDetails], int]:
        filters = [TicketRecord.tenant_id == self._tenant_id]
        if status is not None:
            filters.append(TicketRecord.status == status)
        if user_id is not None:
            filters.append(RentalRecord.user_id == user_id)
        if lot_id is not None:
            filters.append(RentalRecord.lot_id == lot_id)
        if rental_id is not None:
            filters.append(TicketRecord.rental_id == rental_id)
        if created_from is not None:
            filters.append(TicketRecord.created_at >= created_from)
        if created_to is not None:
            filters.append(TicketRecord.created_at < created_to)
        result = await self._session.execute(
            self._with_details()
            .where(*filters)
            .order_by(TicketRecord.created_at.desc(), TicketRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(TicketRecord)
            .join(RentalRecord, self._rental_link())
            .where(*filters)
        )
        return [(ticket, lot, user) for ticket, lot, user in result], int(total or 0)

    async def list_for_rental(self, rental_id: UUID, *, user_id: UUID) -> list[TicketDetails]:
        result = await self._session.execute(
            self._with_details()
            .where(
                TicketRecord.tenant_id == self._tenant_id,
                TicketRecord.rental_id == rental_id,
                RentalRecord.user_id == user_id,
            )
            .order_by(TicketRecord.created_at.desc(), TicketRecord.id.desc())
        )
        return [(ticket, lot, user) for ticket, lot, user in result]

    async def count_for_rental(self, rental_id: UUID, *, start: datetime, end: datetime) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(TicketRecord)
                .where(
                    TicketRecord.tenant_id == self._tenant_id,
                    TicketRecord.rental_id == rental_id,
                    TicketRecord.created_at >= start,
                    TicketRecord.created_at < end,
                )
            )
            or 0
        )

    async def lock_photo_ids(self, user_id: UUID, file_ids: Sequence[UUID]) -> set[UUID]:
        if not file_ids:
            return set()
        # Lock in the same order for overlapping submissions, and hold the rows
        # until the attachment links commit so the orphan purge cannot overtake them.
        return set(
            await self._session.scalars(
                select(FileRecord.id)
                .where(
                    FileRecord.tenant_id == self._tenant_id,
                    FileRecord.uploaded_by == user_id,
                    FileRecord.id.in_(file_ids),
                    FileRecord.purpose == "ticket_photo",
                    FileRecord.public_url.is_(None),
                    FileRecord.is_ready.is_(True),
                    FileRecord.is_purging.is_(False),
                )
                .order_by(FileRecord.id)
                .with_for_update()
            )
        )

    async def photos_for_tickets(self, ticket_ids: Sequence[UUID]) -> dict[UUID, list[FileRecord]]:
        if not ticket_ids:
            return {}
        result = await self._session.execute(
            select(TicketAttachmentRecord.ticket_id, FileRecord)
            .join(
                FileRecord,
                and_(
                    FileRecord.tenant_id == TicketAttachmentRecord.tenant_id,
                    FileRecord.id == TicketAttachmentRecord.file_id,
                ),
            )
            .where(
                TicketAttachmentRecord.tenant_id == self._tenant_id,
                TicketAttachmentRecord.ticket_id.in_(ticket_ids),
            )
            .order_by(TicketAttachmentRecord.ticket_id, TicketAttachmentRecord.position)
        )
        photos: dict[UUID, list[FileRecord]] = {}
        for ticket_id, file_record in result:
            photos.setdefault(ticket_id, []).append(file_record)
        return photos

    @staticmethod
    def _rental_link() -> ColumnElement[bool]:
        return and_(
            RentalRecord.tenant_id == TicketRecord.tenant_id,
            RentalRecord.id == TicketRecord.rental_id,
        )

    @classmethod
    def _with_details(cls) -> Select[TicketRecord, LotRecord, User]:
        return (
            select(TicketRecord, LotRecord, User)
            .join_from(TicketRecord, RentalRecord, cls._rental_link())
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
