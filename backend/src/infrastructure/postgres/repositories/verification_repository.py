from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer
from sqlalchemy.sql.elements import ColumnElement

from app.models import User
from src.application.dtos.verification_dto import (
    AdminUserRef,
    AdminVerificationRequestSummary,
    VerificationDecision,
    VerificationDocumentPurpose,
    VerificationRequestPage,
    VerificationRequestSummary,
)
from src.domain.entities.user_account import VerificationStatus
from src.infrastructure.postgres.models.file_record import FileRecord
from src.infrastructure.postgres.models.verification_request_record import (
    VerificationDocumentRecord,
    VerificationRequestRecord,
)


class VerificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.tenant_id = UUID(str(session.info["tenant_id"]))

    async def lock_user(self, user_id: UUID) -> User | None:
        return await self._session.scalar(
            select(User)
            .where(User.tenant_id == self.tenant_id, User.id == user_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )

    async def has_active_request(self, user_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        VerificationRequestRecord.tenant_id == self.tenant_id,
                        VerificationRequestRecord.user_id == user_id,
                        VerificationRequestRecord.status.in_(("pending", "approved")),
                    )
                )
            )
        )

    async def invalid_documents(
        self, user_id: UUID, documents: Mapping[VerificationDocumentPurpose, UUID]
    ) -> list[VerificationDocumentPurpose]:
        results = await self._session.execute(
            select(FileRecord.id, FileRecord.purpose)
            .where(
                FileRecord.tenant_id == self.tenant_id,
                FileRecord.uploaded_by == user_id,
                FileRecord.id.in_(documents.values()),
                FileRecord.public_url.is_(None),
                FileRecord.is_ready.is_(True),
                FileRecord.is_purging.is_(False),
            )
            .order_by(FileRecord.id)
            .with_for_update()
        )
        purposes = {file_id: purpose for file_id, purpose in results}
        return [
            purpose for purpose, file_id in documents.items() if purposes.get(file_id) != purpose
        ]

    async def create(
        self,
        request_id: UUID,
        user: User,
        passport_enc: str,
        documents: Mapping[VerificationDocumentPurpose, UUID],
    ) -> VerificationRequestSummary:
        record = VerificationRequestRecord(
            id=request_id, tenant_id=self.tenant_id, user_id=user.id, passport_enc=passport_enc
        )
        self._session.add(record)
        user.verification_status = "pending"
        await self._session.flush()
        self._session.add_all(
            [
                VerificationDocumentRecord(
                    tenant_id=self.tenant_id,
                    request_id=request_id,
                    purpose=purpose,
                    file_id=file_id,
                )
                for purpose, file_id in documents.items()
            ]
        )
        await self._session.flush()
        return VerificationRequestSummary.model_validate(record)

    async def list_own(
        self, user_id: UUID, *, limit: int, offset: int
    ) -> VerificationRequestPage[VerificationRequestSummary]:
        filters = (
            VerificationRequestRecord.tenant_id == self.tenant_id,
            VerificationRequestRecord.user_id == user_id,
        )
        result = await self._session.scalars(
            select(VerificationRequestRecord)
            .where(*filters)
            .order_by(
                VerificationRequestRecord.created_at.desc(), VerificationRequestRecord.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return VerificationRequestPage[VerificationRequestSummary](
            items=[VerificationRequestSummary.model_validate(record) for record in result],
            total=await self._count(filters),
            limit=limit,
            offset=offset,
        )

    async def get_own(self, request_id: UUID, user_id: UUID) -> VerificationRequestSummary | None:
        record = await self._session.scalar(
            select(VerificationRequestRecord).where(
                VerificationRequestRecord.tenant_id == self.tenant_id,
                VerificationRequestRecord.id == request_id,
                VerificationRequestRecord.user_id == user_id,
            )
        )
        return None if record is None else VerificationRequestSummary.model_validate(record)

    async def list_admin(
        self, *, status: VerificationStatus | None, limit: int, offset: int
    ) -> VerificationRequestPage[AdminVerificationRequestSummary]:
        filters = [VerificationRequestRecord.tenant_id == self.tenant_id]
        if status is not None:
            filters.append(VerificationRequestRecord.status == status)
        results = await self._session.execute(
            self._select_with_user()
            .where(*filters)
            .order_by(
                VerificationRequestRecord.created_at.desc(), VerificationRequestRecord.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return VerificationRequestPage[AdminVerificationRequestSummary](
            items=[
                self.admin_summary(record, AdminUserRef(id=user_id, name=name, email=email))
                for record, user_id, name, email in results
            ],
            total=await self._count(filters),
            limit=limit,
            offset=offset,
        )

    async def get_admin(
        self, request_id: UUID
    ) -> tuple[AdminVerificationRequestSummary, str] | None:
        result = await self._session.execute(
            self._select_with_user()
            .options(undefer(VerificationRequestRecord.passport_enc))
            .where(
                VerificationRequestRecord.tenant_id == self.tenant_id,
                VerificationRequestRecord.id == request_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        record, user_id, name, email = row
        return (
            self.admin_summary(record, AdminUserRef(id=user_id, name=name, email=email)),
            record.passport_enc,
        )

    async def document_keys(
        self, request_id: UUID, user_id: UUID
    ) -> list[tuple[VerificationDocumentPurpose, str]]:
        results = await self._session.execute(
            select(VerificationDocumentRecord.purpose, FileRecord.object_key)
            .join(
                FileRecord,
                and_(
                    FileRecord.id == VerificationDocumentRecord.file_id,
                    FileRecord.tenant_id == VerificationDocumentRecord.tenant_id,
                ),
            )
            .where(
                VerificationDocumentRecord.tenant_id == self.tenant_id,
                VerificationDocumentRecord.request_id == request_id,
                VerificationDocumentRecord.purpose == FileRecord.purpose,
                FileRecord.uploaded_by == user_id,
                FileRecord.public_url.is_(None),
                FileRecord.is_ready.is_(True),
                FileRecord.is_purging.is_(False),
            )
            .order_by(VerificationDocumentRecord.purpose)
        )
        return [(cast(VerificationDocumentPurpose, purpose), key) for purpose, key in results]

    async def lock_request_for_decision(
        self, request_id: UUID
    ) -> tuple[VerificationRequestRecord, User] | None:
        filters = (
            VerificationRequestRecord.tenant_id == self.tenant_id,
            VerificationRequestRecord.id == request_id,
        )
        user_id = await self._session.scalar(
            select(VerificationRequestRecord.user_id).where(*filters)
        )
        if user_id is None:
            return None
        # Match creation's lock order. NO KEY UPDATE allows other transactions'
        # foreign-key checks while serializing changes to the user's status.
        user = await self.lock_user(user_id)
        if user is None:
            return None
        record = await self._session.scalar(
            select(VerificationRequestRecord).where(*filters).with_for_update()
        )
        return None if record is None else (record, user)

    @staticmethod
    def decide(
        record: VerificationRequestRecord,
        user: User,
        *,
        reviewer_id: UUID,
        decision: VerificationDecision,
        comment: str | None,
    ) -> AdminVerificationRequestSummary:
        record.status = decision
        record.admin_comment = comment
        record.reviewed_at = datetime.now(UTC)
        record.reviewed_by = reviewer_id
        record.version += 1
        user.verification_status = decision
        return VerificationRepository.admin_summary(record, AdminUserRef.model_validate(user))

    @staticmethod
    def admin_summary(
        record: VerificationRequestRecord, user: AdminUserRef
    ) -> AdminVerificationRequestSummary:
        return AdminVerificationRequestSummary.from_summary(
            VerificationRequestSummary.model_validate(record), user
        )

    @staticmethod
    def _select_with_user() -> Select[VerificationRequestRecord, UUID, str, str]:
        return select(VerificationRequestRecord, User.id, User.name, User.email).join(
            User,
            and_(
                User.id == VerificationRequestRecord.user_id,
                User.tenant_id == VerificationRequestRecord.tenant_id,
            ),
        )

    async def _count(self, filters: Sequence[ColumnElement[bool]]) -> int:
        return int(
            await self._session.scalar(
                select(func.count()).select_from(VerificationRequestRecord).where(*filters)
            )
            or 0
        )
