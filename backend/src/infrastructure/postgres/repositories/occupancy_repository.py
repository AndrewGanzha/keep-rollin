from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.repositories.i_occupancy_repository import IOccupancyRepository
from src.domain.entities.occupancy import Occupancy, OccupancyKind, OccupancyStatus
from src.domain.exceptions import LotUnavailableError, OccupancyConflictError
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord

EXCLUSION_VIOLATION = "23P01"


async def insert_occupancy(session: AsyncSession, record: OccupancyRecord) -> None:
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == EXCLUSION_VIOLATION:
            raise OccupancyConflictError("The lot is already occupied for this period") from exc
        raise


def occupancy_from_record(record: OccupancyRecord, window: TimeRange) -> Occupancy:
    start, end = record.period.lower, record.period.upper
    if start is None or end is None:
        start = max(start or window.start, window.start)
        end = min(end or window.end, window.end)
    return Occupancy(
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        lot_id=record.lot_id,
        kind=cast(OccupancyKind, record.kind),
        period=TimeRange(start=start, end=end),
        ref_id=record.ref_id,
        status=cast(OccupancyStatus, record.status),
        reason=record.reason,
        created_by=record.created_by,
    )


class OccupancyRepository(IOccupancyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))

    async def add(self, occupancy: Occupancy) -> None:
        tenant_id = self._tenant_id()
        # Take the same lot lock as status changes before writing occupancy.
        lot_status = await self._session.scalar(
            select(LotRecord.status)
            .where(LotRecord.tenant_id == tenant_id, LotRecord.id == occupancy.lot_id)
            .with_for_update()
        )
        if occupancy.kind == "booking" and lot_status != "active":
            raise LotUnavailableError("The lot is unavailable for booking")
        record = OccupancyRecord(
            id=occupancy.id,
            tenant_id=tenant_id,
            lot_id=occupancy.lot_id,
            kind=occupancy.kind,
            period=Range(
                occupancy.period.start,
                occupancy.period.end,
                bounds="[)",
            ),
            ref_id=occupancy.ref_id,
            status=occupancy.status,
            reason=occupancy.reason,
            created_by=occupancy.created_by,
            created_at=occupancy.created_at,
            updated_at=occupancy.updated_at,
        )
        await insert_occupancy(self._session, record)

    async def list_active(self, *, lot_id: UUID, period: TimeRange) -> list[Occupancy]:
        interval = Range(period.start, period.end, bounds="[)")
        statement = (
            select(OccupancyRecord)
            .where(
                OccupancyRecord.lot_id == lot_id,
                OccupancyRecord.status == "active",
                OccupancyRecord.period.overlaps(interval),
            )
            .order_by(OccupancyRecord.period.asc(), OccupancyRecord.id.asc())
        )
        result = await self._session.execute(statement)
        return [occupancy_from_record(record, period) for record in result.scalars().all()]

    async def release(self, occupancy_id: UUID) -> bool:
        statement = (
            update(OccupancyRecord)
            .where(
                OccupancyRecord.id == occupancy_id,
                OccupancyRecord.status == "active",
            )
            .values(status="released", updated_at=datetime.now(UTC))
        )
        result = await self._session.execute(statement)
        return bool(getattr(result, "rowcount", 0))
