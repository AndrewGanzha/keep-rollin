from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from src.infrastructure.postgres.models.push_subscription_record import PushSubscriptionRecord

MAX_ACTIVE_SUBSCRIPTIONS = 10


class PushSubscriptionLimitReached(Exception):
    pass


class PushSubscriptionEndpointConflict(Exception):
    pass


class PushSubscriptionInactiveActor(Exception):
    pass


@dataclass(frozen=True)
class PushSubscriptionDestination:
    id: UUID
    version: UUID
    endpoint: str = field(repr=False)
    p256dh: str = field(repr=False)
    auth: str = field(repr=False)


class PushSubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    def _owned(self, user_id: UUID) -> ColumnElement[bool]:
        return and_(
            PushSubscriptionRecord.tenant_id == self._tenant_id,
            PushSubscriptionRecord.user_id == user_id,
        )

    def _active(self, now: datetime | None = None) -> ColumnElement[bool]:
        current_time = now if now is not None else func.now()
        return and_(
            PushSubscriptionRecord.disabled_at.is_(None),
            or_(
                PushSubscriptionRecord.expiration_time.is_(None),
                PushSubscriptionRecord.expiration_time > current_time,
            ),
        )

    async def list_for_user(self, user_id: UUID) -> list[PushSubscriptionRecord]:
        record = PushSubscriptionRecord
        return list(
            await self._session.scalars(
                select(record)
                .where(self._owned(user_id), self._active())
                .order_by(record.created_at, record.id)
                .limit(MAX_ACTIVE_SUBSCRIPTIONS)
            )
        )

    async def list_active(
        self, user_id: UUID, *, now: datetime | None = None
    ) -> list[PushSubscriptionDestination]:
        record = PushSubscriptionRecord
        rows = await self._session.execute(
            select(record.id, record.version, record.endpoint, record.p256dh, record.auth)
            .where(self._owned(user_id), self._active(now))
            .order_by(record.created_at, record.id)
            .limit(MAX_ACTIVE_SUBSCRIPTIONS)
        )
        return [PushSubscriptionDestination(*row) for row in rows]

    async def upsert(
        self,
        user_id: UUID,
        *,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None,
        expiration_time: datetime | None,
    ) -> PushSubscriptionRecord:
        # Serialize quota checks for a single account, even when endpoints differ.
        owner = await self._session.scalar(
            select(User.id)
            .where(User.tenant_id == self._tenant_id, User.id == user_id, User.is_active)
            .with_for_update(key_share=True)
        )
        if owner is None:
            raise PushSubscriptionInactiveActor

        record = PushSubscriptionRecord
        active_others = await self._session.scalar(
            select(func.count())
            .select_from(record)
            .where(self._owned(user_id), self._active(), record.endpoint != endpoint)
        )
        if active_others is not None and active_others >= MAX_ACTIVE_SUBSCRIPTIONS:
            raise PushSubscriptionLimitReached

        statement = insert(record).values(
            tenant_id=self._tenant_id,
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
            expiration_time=expiration_time,
            version=uuid4(),
        )
        saved = await self._session.scalar(
            statement.on_conflict_do_update(
                constraint="uq_push_subscription_tenant_endpoint",
                set_={
                    "p256dh": statement.excluded.p256dh,
                    "auth": statement.excluded.auth,
                    "user_agent": statement.excluded.user_agent,
                    "expiration_time": statement.excluded.expiration_time,
                    "version": statement.excluded.version,
                    "disabled_at": None,
                    "updated_at": func.now(),
                },
                where=self._owned(user_id),
            )
            .returning(record)
            .execution_options(populate_existing=True)
        )
        if saved is None:
            raise PushSubscriptionEndpointConflict
        return saved

    async def delete(self, user_id: UUID, subscription_id: UUID) -> None:
        await self._session.execute(
            delete(PushSubscriptionRecord).where(
                self._owned(user_id), PushSubscriptionRecord.id == subscription_id
            )
        )

    async def invalidate(
        self, user_id: UUID, subscription_id: UUID, *, version: UUID, now: datetime | None = None
    ) -> bool:
        record = PushSubscriptionRecord
        invalidated = await self._session.scalar(
            update(record)
            .where(
                self._owned(user_id),
                record.id == subscription_id,
                record.version == version,
                record.disabled_at.is_(None),
            )
            .values(disabled_at=now if now is not None else func.now())
            .returning(record.id)
        )
        return invalidated is not None
