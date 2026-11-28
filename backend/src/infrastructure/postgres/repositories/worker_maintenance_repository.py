from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from src.application.services.audit import AuditWriter
from src.infrastructure.postgres.models.idempotency_key_record import IdempotencyKeyRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.repositories.audit_repository import AuditRepository


class WorkerMaintenanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    async def return_from_maintenance(self, now: datetime, batch_size: int, trace_id: str) -> int:
        expired = self._expired_maintenance(now)
        eligible = (
            LotRecord.tenant_id == self._tenant_id,
            or_(
                LotRecord.status == "active",
                (LotRecord.status == "maintenance") & ~self._has_return_blocker(now),
            ),
        )
        locked_lots = (
            await self._session.scalars(
                select(LotRecord.id)
                .where(*eligible, expired.is_not(None))
                .order_by(LotRecord.id)
                .limit(batch_size)
                .with_for_update(of=LotRecord, skip_locked=True)
            )
        ).all()
        if not locked_lots:
            return 0

        # Also release elapsed periods when staff has already returned the lot to active.
        # Reread blockers under the lot locks before touching occupancy. A concurrent
        # calendar writer may have committed after the candidate query took its snapshot.
        releasable = (
            select(expired).select_from(LotRecord).where(*eligible, LotRecord.id.in_(locked_lots))
        )
        restored_lots = (
            await self._session.scalars(
                update(OccupancyRecord)
                .where(
                    OccupancyRecord.tenant_id == self._tenant_id,
                    OccupancyRecord.id.in_(releasable),
                    OccupancyRecord.status == "active",
                )
                .values(status="released", updated_at=now)
                .returning(OccupancyRecord.lot_id)
            )
        ).all()
        if not restored_lots:
            return 0

        returned = await self._session.scalars(
            update(LotRecord)
            .where(
                LotRecord.tenant_id == self._tenant_id,
                LotRecord.id.in_(restored_lots),
                LotRecord.status == "maintenance",
            )
            .values(status="active", version=LotRecord.version + 1, updated_at=now)
            .returning(LotRecord.id)
        )
        audit = AuditWriter(AuditRepository(self._session), tenant_id=self._tenant_id)
        for lot_id in returned:
            await audit.record(
                action="lot.status_changed",
                actor_id=None,
                actor_role="system",
                entity_type="lot",
                entity_id=lot_id,
                metadata={"old_status": "maintenance", "new_status": "active"},
                request_id=trace_id,
                created_at=now,
            )
        return len(restored_lots)

    def _expired_maintenance(self, now: datetime) -> ScalarSelect[UUID]:
        occupancy = OccupancyRecord
        end = func.upper(occupancy.period)
        # A ticket opens a finite [created_at, maintenance_until) interval with the lot
        # as its reference. Earlier calendar records may use the same kind and ref_id.
        return (
            select(occupancy.id)
            .where(
                occupancy.tenant_id == LotRecord.tenant_id,
                occupancy.lot_id == LotRecord.id,
                occupancy.kind == "maintenance",
                occupancy.status == "active",
                occupancy.ref_id == LotRecord.id,
                occupancy.created_by.is_not(None),
                occupancy.reason.is_(None),
                func.lower(occupancy.period) == occupancy.created_at,
                func.lower_inc(occupancy.period),
                ~func.upper_inc(occupancy.period),
                func.isfinite(end),
                end <= now,
            )
            .order_by(end.desc(), occupancy.id)
            .limit(1)
            .correlate(LotRecord)
            .scalar_subquery()
        )

    def _has_return_blocker(self, now: datetime) -> ColumnElement[bool]:
        occupancy = OccupancyRecord
        # Calendar bookings keep their own windows. A booking due at the end of
        # maintenance needs the lot restored before the rental can become active.
        return or_(
            select(RentalRecord.id)
            .where(
                RentalRecord.tenant_id == LotRecord.tenant_id,
                RentalRecord.lot_id == LotRecord.id,
                RentalRecord.status.in_(("active", "overdue")),
            )
            .exists(),
            select(occupancy.id)
            .where(
                occupancy.tenant_id == LotRecord.tenant_id,
                occupancy.lot_id == LotRecord.id,
                occupancy.status == "active",
                or_(
                    and_(
                        occupancy.kind.in_(("block", "maintenance")),
                        occupancy.period.contains(now),
                    ),
                    and_(
                        occupancy.kind == "maintenance",
                        occupancy.ref_id == LotRecord.id,
                        or_(func.upper_inf(occupancy.period), func.upper(occupancy.period) > now),
                    ),
                ),
            )
            .exists(),
        )

    async def delete_expired_idempotency_keys(self, now: datetime, batch_size: int) -> int:
        key = IdempotencyKeyRecord
        expired = (key.tenant_id == self._tenant_id, key.expires_at <= now)
        selected = (
            select(key.user_id, key.key)
            .where(*expired)
            .order_by(key.expires_at, key.user_id, key.key)
            .limit(batch_size)
        )
        # DELETE rechecks expiration after any concurrent reservation refreshes the row.
        removed = await self._session.scalars(
            delete(key)
            .where(*expired, tuple_(key.user_id, key.key).in_(selected))
            .returning(key.key)
        )
        return len(removed.all())
