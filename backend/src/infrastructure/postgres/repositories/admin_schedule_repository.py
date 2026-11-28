from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, any_, bindparam, select
from sqlalchemy.dialects.postgresql import ARRAY, Range
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, User
from src.application.dtos.admin_schedule_dto import (
    AdminSchedule,
    ScheduleBlockInterval,
    ScheduleInterval,
    ScheduleLot,
    ScheduleRentalInterval,
    ScheduleRentalStatus,
)
from src.application.dtos.battery_stock_dto import BatteryStock
from src.application.dtos.lot_dto import RentalUnit
from src.domain.entities.lot import LotStatus
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.repositories.battery_stock_repository import BatteryStockRepository


class AdminScheduleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    async def tenant_timezone(self) -> str | None:
        return await self._session.scalar(
            select(Tenant.timezone).where(Tenant.id == self._tenant_id)
        )

    async def get_schedule(self, *, period: TimeRange, category_id: UUID | None) -> AdminSchedule:
        now = datetime.now(UTC)
        lots = await self._lots(category_id)
        intervals = await self._intervals(period, [lot.id for lot in lots]) if lots else []
        stocks = await BatteryStockRepository(self._session).list(now=now)
        return AdminSchedule(
            lots=lots,
            intervals=intervals,
            battery_stock=[
                BatteryStock(
                    battery_type=stock.battery_type,
                    name=stock.name,
                    quantity=stock.quantity,
                    peak_committed=peak,
                )
                for stock, peak in stocks
            ],
        )

    async def _lots(self, category_id: UUID | None) -> list[ScheduleLot]:
        query = (
            select(
                LotRecord.id,
                LotRecord.name,
                LotRecord.category_id,
                LotRecord.status,
                LotRecord.battery_type,
                LotRecord.rental_unit,
            )
            .where(LotRecord.tenant_id == self._tenant_id)
            .order_by(LotRecord.name, LotRecord.id)
        )
        if category_id is not None:
            query = query.where(LotRecord.category_id == category_id)
        return [
            ScheduleLot(
                id=lot_id,
                name=name,
                category_id=lot_category,
                status=cast(LotStatus, status),
                battery_type=battery_type,
                rental_unit=cast(RentalUnit, rental_unit),
            )
            for lot_id, name, lot_category, status, battery_type, rental_unit in (
                await self._session.execute(query)
            )
        ]

    async def _intervals(self, period: TimeRange, lot_ids: list[UUID]) -> list[ScheduleInterval]:
        # Share the fetched lot IDs across reads without a bind parameter per lot.
        selected_lots = any_(bindparam("selected_lots", lot_ids, type_=ARRAY(PGUUID())))
        rentals = await self._session.execute(
            select(
                RentalRecord.id,
                RentalRecord.lot_id,
                RentalRecord.start_time,
                RentalRecord.end_time,
                RentalRecord.status,
                RentalRecord.battery_count,
                User.name,
            )
            .join(
                User,
                and_(User.tenant_id == RentalRecord.tenant_id, User.id == RentalRecord.user_id),
            )
            .where(
                RentalRecord.tenant_id == self._tenant_id,
                RentalRecord.lot_id == selected_lots,
                RentalRecord.status != "cancelled",
                RentalRecord.start_time < period.end,
                RentalRecord.end_time > period.start,
            )
        )
        intervals: list[ScheduleInterval] = [
            ScheduleRentalInterval(
                id=rental_id,
                lot_id=lot_id,
                kind="rental",
                start_time=max(start, period.start),
                end_time=min(end, period.end),
                clipped_start=start < period.start,
                clipped_end=end > period.end,
                rental_id=rental_id,
                status=cast(ScheduleRentalStatus, status),
                battery_count=count,
                user_name=user_name,
            )
            for rental_id, lot_id, start, end, status, count, user_name in rentals
        ]
        blocks = await self._session.execute(
            select(
                OccupancyRecord.id,
                OccupancyRecord.lot_id,
                OccupancyRecord.period,
                OccupancyRecord.reason,
            ).where(
                OccupancyRecord.tenant_id == self._tenant_id,
                OccupancyRecord.lot_id == selected_lots,
                OccupancyRecord.status == "active",
                OccupancyRecord.kind == "block",
                OccupancyRecord.period.overlaps(Range(period.start, period.end, bounds="[)")),
            )
        )
        intervals.extend(
            ScheduleBlockInterval(
                id=block_id,
                lot_id=lot_id,
                kind="block",
                start_time=bounds.lower or period.start,
                end_time=bounds.upper or period.end,
                clipped_start=bounds.lower is None or bounds.lower < period.start,
                clipped_end=bounds.upper is None or bounds.upper > period.end,
                block_id=block_id,
                reason=reason or "",
            )
            for block_id, lot_id, bounds, reason in blocks
        )
        return sorted(intervals, key=lambda item: (item.start_time, item.lot_id, item.id))
