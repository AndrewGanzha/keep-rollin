from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.repositories.i_offer_repository import (
    IOfferRepository,
    OfferAcceptanceState,
)
from src.domain.entities.offer import (
    OfferAcceptance,
    OfferNotActiveError,
    OfferNotEditableError,
    OfferNotFoundError,
    OfferStatus,
    OfferVersion,
)
from src.infrastructure.postgres.models.offer_acceptance_record import OfferAcceptanceRecord
from src.infrastructure.postgres.models.offer_version_record import OfferVersionRecord


class OfferRepository(IOfferRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))

    async def list_versions(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[OfferVersion], int]:
        tenant_id = self._tenant_id()
        total = await self._session.scalar(
            select(func.count())
            .select_from(OfferVersionRecord)
            .where(OfferVersionRecord.tenant_id == tenant_id)
        )
        result = await self._session.execute(
            select(OfferVersionRecord)
            .where(OfferVersionRecord.tenant_id == tenant_id)
            .order_by(OfferVersionRecord.version.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_domain(record) for record in result.scalars().all()], int(total or 0)

    async def get(self, offer_id: UUID) -> OfferVersion | None:
        result = await self._session.scalar(
            select(OfferVersionRecord).where(
                OfferVersionRecord.tenant_id == self._tenant_id(),
                OfferVersionRecord.id == offer_id,
            )
        )
        return None if result is None else self._to_domain(result)

    async def create_draft(self, *, title: str, body: str) -> OfferVersion:
        tenant_id = self._tenant_id()
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"offer:{tenant_id}", 0)))
        )
        max_version = await self._session.scalar(
            select(func.max(OfferVersionRecord.version)).where(
                OfferVersionRecord.tenant_id == tenant_id
            )
        )
        record = OfferVersionRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            version=int(max_version or 0) + 1,
            title=title,
            body=body,
            status="draft",
        )
        self._session.add(record)
        await self._session.flush()
        return self._to_domain(record)

    async def update_draft(
        self,
        offer_id: UUID,
        *,
        changes: Mapping[str, object],
    ) -> OfferVersion:
        result = await self._session.execute(
            update(OfferVersionRecord)
            .where(
                OfferVersionRecord.tenant_id == self._tenant_id(),
                OfferVersionRecord.id == offer_id,
                OfferVersionRecord.status == "draft",
            )
            .values(**changes, updated_at=func.now())
            .returning(OfferVersionRecord.id)
        )
        if result.scalar_one_or_none() is None:
            existing = await self.get(offer_id)
            if existing is None:
                raise OfferNotFoundError("Offer not found")
            raise OfferNotEditableError("Only drafts can be edited")
        updated = await self.get(offer_id)
        if updated is None:
            raise OfferNotFoundError("Offer not found")
        return updated

    async def publish(self, offer_id: UUID) -> OfferVersion:
        tenant_id = self._tenant_id()
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"offer:{tenant_id}", 0)))
        )
        target = await self._session.scalar(
            select(OfferVersionRecord)
            .where(
                OfferVersionRecord.tenant_id == tenant_id,
                OfferVersionRecord.id == offer_id,
            )
            .with_for_update()
        )
        if target is None:
            raise OfferNotFoundError("Offer not found")
        if target.status != "draft":
            raise OfferNotEditableError("Only drafts can be published")
        now = datetime.now(UTC)
        await self._session.execute(
            update(OfferVersionRecord)
            .where(
                OfferVersionRecord.tenant_id == tenant_id,
                OfferVersionRecord.status == "active",
            )
            .values(status="archived", updated_at=now)
        )
        target.status = "active"
        target.published_at = now
        target.updated_at = now
        await self._session.flush()
        return self._to_domain(target)

    async def get_current(self) -> OfferVersion | None:
        record = await self._session.scalar(
            select(OfferVersionRecord).where(
                OfferVersionRecord.tenant_id == self._tenant_id(),
                OfferVersionRecord.status == "active",
            )
        )
        return None if record is None else self._to_domain(record)

    async def accept(
        self,
        *,
        user_id: UUID,
        offer_version_id: UUID,
        ip: str | None,
    ) -> OfferAcceptanceState:
        tenant_id = self._tenant_id()
        offer = await self._session.scalar(
            select(OfferVersionRecord).where(
                OfferVersionRecord.tenant_id == tenant_id,
                OfferVersionRecord.id == offer_version_id,
            )
        )
        if offer is None:
            raise OfferNotFoundError("Offer not found")
        if offer.status != "active":
            raise OfferNotActiveError("Only the active offer can be accepted")
        await self._session.execute(
            insert(OfferAcceptanceRecord)
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                user_id=user_id,
                offer_version_id=offer_version_id,
                ip=ip,
            )
            .on_conflict_do_nothing(
                constraint="uq_offer_acceptance_user_version",
            )
        )
        state = await self._acceptance_state(user_id, offer_version_id)
        if state is None:
            raise OfferNotFoundError("Offer acceptance not found")
        return state

    async def list_acceptances(self, *, user_id: UUID) -> list[OfferAcceptanceState]:
        result = await self._session.execute(
            select(OfferAcceptanceRecord, OfferVersionRecord.version)
            .join(
                OfferVersionRecord,
                OfferVersionRecord.id == OfferAcceptanceRecord.offer_version_id,
            )
            .where(
                OfferAcceptanceRecord.tenant_id == self._tenant_id(),
                OfferAcceptanceRecord.user_id == user_id,
            )
            .order_by(OfferAcceptanceRecord.accepted_at.desc())
        )
        return [
            OfferAcceptanceState(
                acceptance=self._acceptance_to_domain(record),
                version_number=int(version),
            )
            for record, version in result.all()
        ]

    async def has_accepted_current(self, *, user_id: UUID) -> bool:
        tenant_id = self._tenant_id()
        value = await self._session.scalar(
            select(OfferAcceptanceRecord.id)
            .join(
                OfferVersionRecord,
                OfferVersionRecord.id == OfferAcceptanceRecord.offer_version_id,
            )
            .where(
                OfferAcceptanceRecord.tenant_id == tenant_id,
                OfferAcceptanceRecord.user_id == user_id,
                OfferVersionRecord.status == "active",
            )
            .limit(1)
        )
        return value is not None

    async def _acceptance_state(
        self,
        user_id: UUID,
        offer_version_id: UUID,
    ) -> OfferAcceptanceState | None:
        row = (
            await self._session.execute(
                select(OfferAcceptanceRecord, OfferVersionRecord.version)
                .join(
                    OfferVersionRecord,
                    OfferVersionRecord.id == OfferAcceptanceRecord.offer_version_id,
                )
                .where(
                    OfferAcceptanceRecord.tenant_id == self._tenant_id(),
                    OfferAcceptanceRecord.user_id == user_id,
                    OfferAcceptanceRecord.offer_version_id == offer_version_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        record, version = row
        return OfferAcceptanceState(
            acceptance=self._acceptance_to_domain(record),
            version_number=int(version),
        )

    @staticmethod
    def _to_domain(record: OfferVersionRecord) -> OfferVersion:
        return OfferVersion(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            version=record.version,
            title=record.title,
            body=record.body,
            status=cast(OfferStatus, record.status),
            published_at=record.published_at,
        )

    @staticmethod
    def _acceptance_to_domain(record: OfferAcceptanceRecord) -> OfferAcceptance:
        return OfferAcceptance(
            id=record.id,
            user_id=record.user_id,
            offer_version_id=record.offer_version_id,
            accepted_at=record.accepted_at,
            ip=record.ip,
        )
