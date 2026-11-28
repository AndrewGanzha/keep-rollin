from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.postgres.repositories.rental_lifecycle_repository import (
    RentalLifecycleRepository,
)
from src.infrastructure.postgres.repositories.rental_reminder_repository import (
    RentalReminderRepository,
)
from src.infrastructure.postgres.repositories.worker_maintenance_repository import (
    WorkerMaintenanceRepository,
)

Job = Callable[[AsyncSession, datetime, int, str], Awaitable[int]]


async def transition_rentals(
    session: AsyncSession, now: datetime, batch_size: int, trace_id: str
) -> int:
    result = await RentalLifecycleRepository(session).process_batch(
        now=now, limit=batch_size, request_id=trace_id
    )
    return result.activated + result.overdue


async def return_maintenance_lots(
    session: AsyncSession, now: datetime, batch_size: int, trace_id: str
) -> int:
    return await WorkerMaintenanceRepository(session).return_from_maintenance(
        now=now, batch_size=batch_size, trace_id=trace_id
    )


async def expire_idempotency_keys(
    session: AsyncSession, now: datetime, batch_size: int, trace_id: str
) -> int:
    return await WorkerMaintenanceRepository(session).delete_expired_idempotency_keys(
        now=now, batch_size=batch_size
    )


async def enqueue_rental_reminders(
    session: AsyncSession, now: datetime, batch_size: int, trace_id: str
) -> int:
    return await RentalReminderRepository(session).enqueue_due(now=now, limit=batch_size)


JOBS: dict[str, Job] = {
    "rental_reminders": enqueue_rental_reminders,
    "rental_lifecycle": transition_rentals,
    "maintenance_expiry": return_maintenance_lots,
    "idempotency_expiry": expire_idempotency_keys,
}
