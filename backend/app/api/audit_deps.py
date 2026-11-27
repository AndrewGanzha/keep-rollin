from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import get_current_user
from app.api.deps import get_db_session
from src.application.services.audit import AuditWriter
from src.domain.entities.user_account import UserAccount
from src.infrastructure.postgres.repositories.audit_repository import AuditRepository


class StaffAudit:
    def __init__(
        self,
        request: Request,
        actor: Annotated[UserAccount, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> None:
        self.tenant_id = cast(UUID, request.state.tenant_id)
        self._writer = AuditWriter(AuditRepository(session), tenant_id=self.tenant_id)
        self._request = request
        self._actor = actor

    async def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: UUID,
        metadata: dict[str, object] | None = None,
    ) -> None:
        client = self._request.client
        await self._writer.record(
            action=action,
            actor_id=self._actor.id,
            actor_role=self._actor.role,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata,
            ip=client.host if client else None,
            request_id=cast(str, self._request.state.request_id),
        )
