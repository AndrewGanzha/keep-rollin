from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from src.application.repositories.i_auth_repository import IAuthRepository
from src.application.services.audit import AuditWriter
from src.application.services.auth import AuthService
from src.application.services.password_executor import run_password_work
from src.domain.entities.user_account import InvalidTokenError, UserAccount
from src.domain.policies.password_policy import ensure_password_not_compromised
from src.infrastructure.postgres.repositories.admin_user_repository import (
    AdminUserInfo,
    AdminUserRepository,
)


class AdminUserError(Exception):
    pass


class AdminUserNotFoundError(AdminUserError):
    pass


class SelfDeactivationError(AdminUserError):
    pass


class LastOwnerError(AdminUserError):
    pass


class ForbiddenAdminActionError(AdminUserError):
    pass


class PasswordHasherPort(Protocol):
    def hash(self, password: str) -> str: ...


@dataclass(frozen=True)
class AdminUserPage:
    items: list[AdminUserInfo]
    total: int
    limit: int
    offset: int


class AdminUserService:
    def __init__(
        self,
        repository: AdminUserRepository,
        auth_repository: IAuthRepository,
        auth_service: AuthService,
        password_hasher: PasswordHasherPort,
        audit: AuditWriter,
        *,
        password_work_timeout_seconds: float = 5.0,
    ) -> None:
        self._repository = repository
        self._auth_repository = auth_repository
        self._auth_service = auth_service
        self._password_hasher = password_hasher
        self._audit = audit
        self._password_work_timeout_seconds = password_work_timeout_seconds

    async def list_users(
        self,
        *,
        role: str | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> AdminUserPage:
        items, total = await self._repository.list_users(
            role=role,
            query=query,
            limit=limit,
            offset=offset,
        )
        return AdminUserPage(items=items, total=total, limit=limit, offset=offset)

    async def create(
        self,
        *,
        actor: UserAccount,
        email: str,
        name: str | None,
        password: str,
        mfa_code: str | None,
        ip: str | None,
        request_id: str | None,
    ) -> AdminUserInfo:
        await self._auth_service.ensure_step_up_available(user_id=actor.id)
        normalized = email.strip().lower()
        ensure_password_not_compromised(password)
        password_hash = await run_password_work(
            lambda: self._password_hasher.hash(password),
            timeout_seconds=self._password_work_timeout_seconds,
        )
        await self._repository.lock_tenant()
        actor_record = await self._auth_repository.get_by_id_for_update(actor.id)
        if actor_record is None or not actor_record.is_active or actor_record.role != "owner":
            raise ForbiddenAdminActionError("Owner role is required")
        if actor_record.token_version != actor.token_version:
            raise InvalidTokenError("Access token has been revoked")
        await self._auth_service.verify_step_up(user_id=actor.id, code=mfa_code)

        resolved_name = (name or "").strip() or normalized.split("@", 1)[0]
        created = await self._repository.create_admin(
            email=normalized,
            name=resolved_name[:120],
            password_hash=password_hash,
        )
        await self._audit.record(
            action="admin.created",
            actor_id=actor.id,
            actor_role="owner",
            entity_type="user",
            entity_id=created.id,
            metadata={"role": "admin"},
            ip=ip,
            request_id=request_id,
        )
        return created

    async def deactivate(
        self,
        *,
        actor: UserAccount,
        target_id: UUID,
        ip: str | None,
        request_id: str | None,
    ) -> bool:
        await self._repository.lock_tenant()
        records = {}
        for user_id in sorted({actor.id, target_id}, key=str):
            records[user_id] = await self._repository.get_for_update(user_id)
        actor_record = records[actor.id]
        target = records[target_id]
        if actor_record is None or not actor_record.is_active or actor_record.role != "owner":
            raise ForbiddenAdminActionError("Owner role is required")
        if actor_record.token_version != actor.token_version:
            raise InvalidTokenError("Access token has been revoked")
        if target is None:
            raise AdminUserNotFoundError("User was not found")
        if target.id == actor.id:
            raise SelfDeactivationError("Cannot deactivate the current user")
        if not target.is_active:
            return False
        if target.role == "owner" and await self._repository.count_active_owners() <= 1:
            raise LastOwnerError("Cannot deactivate the last active owner")

        await self._repository.deactivate(
            target.id,
            token_version=target.token_version + 1,
        )
        await self._repository.revoke_all_sessions(target.id, revoked_at=datetime.now(UTC))
        action = "admin.deactivated" if target.role in ("owner", "admin") else "user.deactivated"
        await self._audit.record(
            action=action,
            actor_id=actor.id,
            actor_role="owner",
            entity_type="user",
            entity_id=target.id,
            metadata={"role": target.role},
            ip=ip,
            request_id=request_id,
        )
        return True
