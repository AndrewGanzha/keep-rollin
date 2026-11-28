from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import ColumnElement, and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class NotificationPreferencesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    def _active_user(self, user_id: UUID) -> ColumnElement[bool]:
        return and_(User.tenant_id == self._tenant_id, User.id == user_id, User.is_active)

    async def get(self, user_id: UUID) -> dict[str, object] | None:
        return await self._session.scalar(
            select(User.notification_preferences).where(self._active_user(user_id))
        )

    async def update(
        self,
        user_id: UUID,
        *,
        push_enabled: bool | None,
        email_by_event: Mapping[str, bool],
    ) -> dict[str, object] | None:
        if push_enabled is None and not email_by_event:
            return await self.get(user_id)

        active_user = self._active_user(user_id)
        current = await self._session.scalar(
            select(User.notification_preferences).where(active_user).with_for_update()
        )
        if current is None:
            return None

        merged = dict(current)
        if push_enabled is not None:
            merged["push_enabled"] = push_enabled
        if email_by_event:
            current_email = current.get("email_by_event")
            merged_email = dict(current_email) if isinstance(current_email, Mapping) else {}
            merged_email.update(email_by_event)
            merged["email_by_event"] = merged_email

        await self._session.execute(
            update(User).where(active_user).values(notification_preferences=merged)
        )
        return merged
