from uuid import UUID

from sqlalchemy import and_, func, select, true
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.repositories.i_public_availability_repository import (
    IPublicAvailabilityRepository,
)
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.repositories.lot_repository import bookable_lot, public_lot_query


class PublicAvailabilityRepository(IPublicAvailabilityRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_occupancy_periods(
        self, *, period: TimeRange, category_id: UUID | None
    ) -> tuple[int, list[tuple[UUID, TimeRange]]]:
        tenant_id = self._session.info.get("tenant_id")
        if not tenant_id:
            raise RuntimeError("tenant context is missing")

        eligible_query = (
            public_lot_query()
            .with_only_columns(LotRecord.id, LotRecord.tenant_id)
            .where(LotRecord.tenant_id == UUID(str(tenant_id)), bookable_lot())
        )
        if category_id is not None:
            eligible_query = eligible_query.where(LotRecord.category_id == category_id)
        eligible_lots = eligible_query.cte("eligible_lots")
        totals = select(func.count().label("lots_total")).select_from(eligible_lots).subquery()

        interval = Range(period.start, period.end, bounds="[)")
        occupied_periods = (
            select(OccupancyRecord.lot_id, OccupancyRecord.period)
            .join(
                eligible_lots,
                and_(
                    OccupancyRecord.tenant_id == eligible_lots.c.tenant_id,
                    OccupancyRecord.lot_id == eligible_lots.c.id,
                ),
            )
            .where(OccupancyRecord.status == "active", OccupancyRecord.period.overlaps(interval))
            .subquery()
        )

        # Keep the total and occupancy records on one statement snapshot, including when no
        # occupancy overlaps the requested period.
        statement = select(
            totals.c.lots_total, occupied_periods.c.lot_id, occupied_periods.c.period
        )
        result = await self._session.execute(
            statement.select_from(totals.outerjoin(occupied_periods, true()))
        )

        rows = result.all()
        lots_total: int = rows[0][0]
        occupancies: list[tuple[UUID, TimeRange]] = []
        for _, lot_id, occupied_period in rows:
            if occupied_period is None:
                continue
            start = max(period.start, occupied_period.lower or period.start)
            end = min(period.end, occupied_period.upper or period.end)
            if start < end:
                occupancies.append((lot_id, TimeRange(start=start, end=end)))
        return lots_total, occupancies
