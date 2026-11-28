from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from src.infrastructure.postgres.models.file_record import AttachmentRecord, FileRecord
from src.infrastructure.postgres.models.verification_request_record import (
    VerificationDocumentRecord,
)


class UnknownLotPhotoError(Exception):
    pass


class FileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _tenant_id(self) -> UUID:
        return UUID(str(self._session.info["tenant_id"]))

    async def set_lot_photos(
        self,
        *,
        lot_id: UUID,
        file_ids: list[UUID] | None = None,
        legacy_urls: list[str] | None = None,
    ) -> list[str]:
        tenant_id = self._tenant_id()
        attachments: list[tuple[int, UUID]] = []
        if file_ids is not None:
            records = await self._session.scalars(
                select(FileRecord)
                .where(
                    FileRecord.tenant_id == tenant_id,
                    FileRecord.id.in_(file_ids),
                    FileRecord.purpose == "lot_photo",
                    FileRecord.is_ready.is_(True),
                )
                .order_by(FileRecord.id)
                .with_for_update()
            )
            by_id = {record.id: record.public_url for record in records if record.public_url}
            urls = []
            for index, file_id in enumerate(file_ids):
                url = by_id.get(file_id)
                if url is None:
                    raise UnknownLotPhotoError("Lot photo was not found")
                urls.append(url)
                attachments.append((index, file_id))
        else:
            urls = legacy_urls or []
            existing = await self._session.execute(
                select(FileRecord.public_url, FileRecord.id)
                .where(
                    FileRecord.tenant_id == tenant_id,
                    FileRecord.purpose == "lot_photo",
                    FileRecord.public_url.in_(urls),
                    FileRecord.is_ready.is_(True),
                )
                .order_by(FileRecord.id)
                .with_for_update()
            )
            by_url = {url: file_id for url, file_id in existing}
            linked_ids: set[UUID] = set()
            for index, url in enumerate(urls):
                linked = by_url.get(url)
                if linked is not None and linked not in linked_ids:
                    attachments.append((index, linked))
                    linked_ids.add(linked)

        await self._session.execute(
            delete(AttachmentRecord).where(
                AttachmentRecord.tenant_id == tenant_id,
                AttachmentRecord.lot_id == lot_id,
            )
        )
        self._session.add_all(
            [
                AttachmentRecord(
                    tenant_id=tenant_id,
                    lot_id=lot_id,
                    file_id=file_id,
                    position=position,
                )
                for position, file_id in attachments
            ]
        )
        await self._session.flush()
        return urls

    @staticmethod
    def _unattached_before(cutoff: datetime) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
        attached = exists().where(
            AttachmentRecord.tenant_id == FileRecord.tenant_id,
            AttachmentRecord.file_id == FileRecord.id,
        )
        verification_document = exists().where(
            VerificationDocumentRecord.tenant_id == FileRecord.tenant_id,
            VerificationDocumentRecord.file_id == FileRecord.id,
        )
        return FileRecord.created_at < cutoff, ~attached & ~verification_document

    async def count_orphans(self, cutoff: datetime) -> int:
        cutoff_filter, unattached = self._unattached_before(cutoff)
        return int(
            await self._session.scalar(
                select(func.count()).select_from(FileRecord).where(cutoff_filter, unattached)
            )
            or 0
        )

    async def lock_orphans(self, cutoff: datetime, *, limit: int) -> list[FileRecord]:
        cutoff_filter, unattached = self._unattached_before(cutoff)
        rows = await self._session.scalars(
            select(FileRecord)
            .where(cutoff_filter, unattached)
            .order_by(FileRecord.created_at, FileRecord.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        candidates = list(rows)
        if not candidates:
            return []
        # A different transaction may have committed a link after the first
        # statement snapshot but before we acquired the file row lock.
        orphan_ids = set(
            await self._session.scalars(
                select(FileRecord.id).where(
                    FileRecord.id.in_([row.id for row in candidates]), unattached
                )
            )
        )
        return [row for row in candidates if row.id in orphan_ids]

    async def delete_claimed_orphan(self, file_id: UUID) -> bool:
        result = await self._session.execute(
            delete(FileRecord)
            .where(FileRecord.id == file_id, FileRecord.is_purging.is_(True))
            .returning(FileRecord.id)
        )
        return result.scalar_one_or_none() is not None
