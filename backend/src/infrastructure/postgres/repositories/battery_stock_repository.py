from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.battery_stock_record import BatteryStockRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord


class BatteryStockNotFoundError(Exception):
    pass


class BatteryStockConflictError(Exception):
    pass


class BatteryStockInUseError(Exception):
    pass


class BatteryStockBelowCommittedError(Exception):
    def __init__(self, peak_committed: int) -> None:
        super().__init__("Battery stock cannot be reduced below peak committed capacity")
        self.peak_committed = peak_committed


class BatteryStockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    async def capacity(self, battery_type: str, period: TimeRange, *, lock: bool = False) -> int:
        stock = await self._get(battery_type, lock=lock)
        if stock is None:
            return 0
        peaks = await self._peaks(
            from_time=period.start, to_time=period.end, battery_type=battery_type
        )
        return max(0, stock.quantity - peaks.get(battery_type, 0))

    async def list(self, *, now: datetime) -> list[tuple[BatteryStockRecord, int]]:
        stocks = (
            await self._session.scalars(
                select(BatteryStockRecord)
                .where(BatteryStockRecord.tenant_id == self._tenant_id)
                .order_by(BatteryStockRecord.battery_type)
            )
        ).all()
        peaks = await self._peaks(from_time=now)
        return [(stock, peaks.get(stock.battery_type, 0)) for stock in stocks]

    async def create(
        self, battery_type: str, name: str, quantity: int
    ) -> tuple[BatteryStockRecord, int]:
        statement = (
            insert(BatteryStockRecord)
            .values(
                tenant_id=self._tenant_id, battery_type=battery_type, name=name, quantity=quantity
            )
            .on_conflict_do_nothing(
                index_elements=[BatteryStockRecord.tenant_id, BatteryStockRecord.battery_type]
            )
            .returning(BatteryStockRecord)
        )
        stock = await self._session.scalar(statement)
        if stock is None:
            raise BatteryStockConflictError("Battery stock already exists for this type")
        return stock, 0

    async def update_quantity(
        self, battery_type: str, quantity: int, *, now: datetime
    ) -> tuple[BatteryStockRecord, int]:
        stock = await self._get(battery_type, lock=True)
        if stock is None:
            raise BatteryStockNotFoundError("Battery stock was not found")
        peaks = await self._peaks(from_time=now, battery_type=battery_type)
        peak = peaks.get(battery_type, 0)
        if quantity < peak:
            raise BatteryStockBelowCommittedError(peak)
        stock.quantity = quantity
        await self._session.flush()
        return stock, peak

    async def delete(self, battery_type: str) -> BatteryStockRecord:
        stock = await self._get(battery_type, lock=True)
        if stock is None:
            raise BatteryStockNotFoundError("Battery stock was not found")
        has_rentals = await self._session.scalar(
            select(
                exists().where(
                    RentalRecord.tenant_id == self._tenant_id,
                    RentalRecord.battery_type == battery_type,
                )
            )
        )
        if has_rentals:
            raise BatteryStockInUseError("Battery stock is referenced by rental history")
        await self._session.delete(stock)
        await self._session.flush()
        return stock

    async def _get(self, battery_type: str, *, lock: bool) -> BatteryStockRecord | None:
        statement = (
            select(BatteryStockRecord)
            .where(
                BatteryStockRecord.tenant_id == self._tenant_id,
                BatteryStockRecord.battery_type == battery_type,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def _peaks(
        self,
        *,
        from_time: datetime,
        to_time: datetime | None = None,
        battery_type: str | None = None,
    ) -> dict[str, int]:
        statement = select(
            RentalRecord.battery_type,
            RentalRecord.start_time,
            RentalRecord.end_time,
            RentalRecord.battery_count,
        ).where(
            RentalRecord.tenant_id == self._tenant_id,
            RentalRecord.battery_type.is_not(None),
            RentalRecord.status.in_(("booked", "active")),
            RentalRecord.end_time > from_time,
        )
        if battery_type is not None:
            statement = statement.where(RentalRecord.battery_type == battery_type)
        if to_time is not None:
            statement = statement.where(RentalRecord.start_time < to_time)

        events: dict[str, dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
        for rental_type, start, end, count in await self._session.execute(statement):
            assert rental_type is not None
            changes = events[rental_type]
            changes[max(start, from_time)] += count
            changes[min(end, to_time) if to_time is not None else end] -= count

        peaks = {}
        for rental_type, changes in events.items():
            committed = 0
            peak = 0
            # Combine starts and ends at the same timestamp to honor half-open periods.
            for timestamp in sorted(changes):
                committed += changes[timestamp]
                peak = max(peak, committed)
            peaks[rental_type] = peak
        return peaks
