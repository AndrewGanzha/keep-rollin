from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, literal, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from src.domain.entities.outbox_message import OutboxMessage
from src.domain.entities.tenant_profile import TenantPolicies
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.models.tenant_settings_record import TenantSettingsRecord

REMINDER_EVENT = "rental.ending_soon"
ACTIVE: ColumnElement[str] = literal_column("'active'")


class RentalReminderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    async def enqueue_due(self, *, now: datetime, limit: int) -> int:
        policies = await self._session.scalar(
            select(TenantSettingsRecord.policies).where(
                TenantSettingsRecord.tenant_id == self._tenant_id
            )
        )
        ahead = TenantPolicies.from_mapping(policies or {}).reminder_hours_before
        rental, outbox = RentalRecord, OutboxMessageRecord
        already_queued = (
            select(outbox.id)
            .where(
                outbox.tenant_id == rental.tenant_id,
                outbox.event_type == REMINDER_EVENT,
                outbox.entity_id == rental.id,
                outbox.user_id == rental.user_id,
                outbox.channel.is_(None),
            )
            .exists()
        )
        due = (
            select(
                rental.tenant_id,
                literal(REMINDER_EVENT),
                rental.id,
                rental.user_id,
                literal(now),
                literal(now),
                literal(now),
            )
            .where(
                rental.tenant_id == self._tenant_id,
                rental.status == ACTIVE,
                rental.end_time > now,
                rental.end_time <= now + timedelta(hours=ahead),
                ~already_queued,
            )
            .order_by(rental.end_time, rental.id)
            .limit(limit)
            # Read-lock the rental only. The job never takes a lot lock.
            .with_for_update(read=True, of=rental, skip_locked=True)
        )
        queued = await self._session.scalars(
            insert(outbox)
            .from_select(
                [
                    "tenant_id",
                    "event_type",
                    "entity_id",
                    "user_id",
                    "available_at",
                    "created_at",
                    "updated_at",
                ],
                due,
                include_defaults=False,
            )
            .on_conflict_do_nothing(constraint="uq_outbox_message_event_chain")
            .returning(outbox.id)
        )
        return len(queued.all())

    async def can_deliver(self, message: OutboxMessage) -> bool:
        if message.event_type != REMINDER_EVENT:
            return True
        if message.entity_id is None or message.user_id is None:
            return False
        rental = RentalRecord
        active = select(rental.id).where(
            rental.tenant_id == self._tenant_id,
            rental.id == message.entity_id,
            rental.user_id == message.user_id,
            rental.status == ACTIVE,
            rental.end_time > func.clock_timestamp(),
        )
        return await self._session.scalar(active) is not None
