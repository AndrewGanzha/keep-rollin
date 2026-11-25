from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.application.repositories.i_occupancy_repository import IOccupancyRepository
from src.domain.entities.occupancy import Occupancy, OccupancyKind
from src.domain.value_objects.time_range import TimeRange


class OccupancyService:
    def __init__(self, repository: IOccupancyRepository) -> None:
        self._repository = repository

    async def reserve(
        self,
        *,
        lot_id: UUID,
        kind: OccupancyKind,
        period: TimeRange,
        ref_id: UUID | None = None,
    ) -> Occupancy:
        now = datetime.now(UTC)
        occupancy = Occupancy(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            lot_id=lot_id,
            kind=kind,
            period=period,
            ref_id=ref_id,
            status="active",
        )
        await self._repository.add(occupancy)
        return occupancy

    async def release(self, occupancy_id: UUID) -> bool:
        return await self._repository.release(occupancy_id)
