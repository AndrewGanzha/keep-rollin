from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant
from src.application.repositories.i_admin_calendar_repository import (
    IAdminCalendarRepository,
)
from src.domain.entities.occupancy import (
    BlockNotFoundError,
    Occupancy,
    TooManyCalendarLotsError,
)
from src.domain.exceptions import InvalidTimeRangeError
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.repositories.occupancy_repository import (
    insert_occupancy,
    occupancy_from_record,
)

MAX_CALENDAR_LOTS = 200


def _align_block_period(period: TimeRange, timezone: ZoneInfo) -> TimeRange:
    local_start = period.start.astimezone(timezone)
    local_end = period.end.astimezone(timezone)
    start_day: date = local_start.date()
    end_day: date = local_end.date()
    if local_end.time() != dt_time.min:
        end_day += timedelta(days=1)
    start_local = datetime.combine(start_day, dt_time.min, tzinfo=timezone)
    end_local = datetime.combine(end_day, dt_time.min, tzinfo=timezone)
    if start_local >= end_local:
        raise InvalidTimeRangeError("Block period must cover at least one local day")
    if (end_local - start_local).days > 366:
        raise InvalidTimeRangeError("Block period must not exceed 366 days")
    return TimeRange(
        start=start_local.astimezone(UTC),
        end=end_local.astimezone(UTC),
    )


class AdminCalendarRepository(IAdminCalendarRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))

    async def list_events(
        self,
        *,
        period: TimeRange,
        category_id: UUID | None,
        lot_id: UUID | None,
        status: str | None,
    ) -> list[Occupancy]:
        filters = self._filters(period, category_id, lot_id, status)
        distinct_lots = (
            await self._session.execute(
                select(func.count(func.distinct(OccupancyRecord.lot_id)))
                .join(LotRecord, LotRecord.id == OccupancyRecord.lot_id)
                .where(*filters)
            )
        ).scalar_one()
        if int(distinct_lots or 0) > MAX_CALENDAR_LOTS:
            raise TooManyCalendarLotsError("calendar filter matches too many lots")
        result = await self._session.execute(
            select(OccupancyRecord)
            .join(LotRecord, LotRecord.id == OccupancyRecord.lot_id)
            .where(*filters)
            .order_by(
                OccupancyRecord.period.asc(),
                OccupancyRecord.lot_id.asc(),
                OccupancyRecord.id.asc(),
            )
        )
        return [occupancy_from_record(record, period) for record in result.scalars().all()]

    async def lot_events(
        self,
        *,
        lot_id: UUID,
        period: TimeRange,
    ) -> list[Occupancy] | None:
        exists = await self._session.scalar(
            select(LotRecord.id).where(
                LotRecord.id == lot_id,
                LotRecord.tenant_id == self._tenant_id(),
            )
        )
        if exists is None:
            return None
        result = await self._session.execute(
            select(OccupancyRecord)
            .where(
                OccupancyRecord.lot_id == lot_id,
                OccupancyRecord.status == "active",
                OccupancyRecord.period.overlaps(Range(period.start, period.end, bounds="[)")),
            )
            .order_by(OccupancyRecord.period.asc(), OccupancyRecord.id.asc())
        )
        return [occupancy_from_record(record, period) for record in result.scalars().all()]

    async def create_block(
        self,
        *,
        lot_id: UUID,
        period: TimeRange,
        reason: str,
        created_by: UUID,
    ) -> Occupancy:
        # Use the same lock order as booking and status changes.
        exists = await self._session.scalar(
            select(LotRecord.id)
            .where(
                LotRecord.id == lot_id,
                LotRecord.tenant_id == self._tenant_id(),
            )
            .with_for_update()
        )
        if exists is None:
            raise BlockNotFoundError("Lot not found")
        aligned = _align_block_period(period, await self._tenant_timezone())
        now = datetime.now(UTC)
        occupancy = Occupancy(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            lot_id=lot_id,
            kind="block",
            period=aligned,
            ref_id=None,
            status="active",
            reason=reason,
            created_by=created_by,
        )
        record = OccupancyRecord(
            id=occupancy.id,
            tenant_id=self._tenant_id(),
            lot_id=occupancy.lot_id,
            kind=occupancy.kind,
            period=Range(
                occupancy.period.start,
                occupancy.period.end,
                bounds="[)",
            ),
            ref_id=None,
            status=occupancy.status,
            reason=reason,
            created_by=created_by,
            created_at=occupancy.created_at,
            updated_at=occupancy.updated_at,
        )
        await insert_occupancy(self._session, record)
        return occupancy

    async def release_block(self, *, lot_id: UUID, block_id: UUID) -> bool:
        tenant_id = self._tenant_id()
        result = await self._session.execute(
            update(OccupancyRecord)
            .where(
                OccupancyRecord.tenant_id == tenant_id,
                OccupancyRecord.id == block_id,
                OccupancyRecord.lot_id == lot_id,
                OccupancyRecord.kind == "block",
                OccupancyRecord.status == "active",
            )
            .values(status="released", updated_at=datetime.now(UTC))
            .returning(OccupancyRecord.id)
        )
        if result.scalar_one_or_none() is not None:
            return True
        exists = await self._session.scalar(
            select(OccupancyRecord.id).where(
                OccupancyRecord.tenant_id == tenant_id,
                OccupancyRecord.id == block_id,
                OccupancyRecord.lot_id == lot_id,
                OccupancyRecord.kind == "block",
            )
        )
        if exists is None:
            raise BlockNotFoundError("Block not found")
        return False

    async def _tenant_timezone(self) -> ZoneInfo:
        timezone = await self._session.scalar(
            select(Tenant.timezone).where(Tenant.id == self._tenant_id())
        )
        if timezone is None:
            raise BlockNotFoundError("Tenant not found")
        try:
            return ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise InvalidTimeRangeError("Tenant timezone is invalid") from exc

    def _filters(
        self,
        period: TimeRange,
        category_id: UUID | None,
        lot_id: UUID | None,
        status: str | None,
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = [
            OccupancyRecord.tenant_id == self._tenant_id(),
            OccupancyRecord.period.overlaps(Range(period.start, period.end, bounds="[)")),
        ]
        if category_id is not None:
            filters.append(LotRecord.category_id == category_id)
        if lot_id is not None:
            filters.append(OccupancyRecord.lot_id == lot_id)
        if status == "booked":
            filters.extend(
                [
                    OccupancyRecord.status == "active",
                    OccupancyRecord.kind == "booking",
                ]
            )
        elif status == "active":
            filters.extend(
                [
                    OccupancyRecord.status == "active",
                    OccupancyRecord.kind.in_(("block", "maintenance")),
                ]
            )
        elif status == "released":
            filters.append(OccupancyRecord.status == "released")
        else:
            filters.append(OccupancyRecord.status == "active")
        return filters
