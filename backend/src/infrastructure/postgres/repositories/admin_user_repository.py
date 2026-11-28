from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from src.domain.entities.user_account import EmailTakenError
from src.infrastructure.postgres.models.refresh_session_record import RefreshSessionRecord

UNIQUE_VIOLATION = "23505"


@dataclass(frozen=True)
class AdminUserInfo:
    id: UUID
    email: str
    name: str
    role: str
    is_active: bool
    mfa_enabled: bool
    created_at: datetime


class AdminUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))

    async def lock_tenant(self) -> None:
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(str(self._tenant_id()), 0)))
        )

    async def list_users(
        self,
        *,
        role: str | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AdminUserInfo], int]:
        filters = []
        if role is not None:
            filters.append(User.role == role)
        if query:
            pattern = f"%{query.strip()}%"
            filters.append(or_(User.email.ilike(pattern), User.name.ilike(pattern)))
        total = await self._session.scalar(select(func.count()).select_from(User).where(*filters))
        result = await self._session.execute(
            select(User)
            .where(*filters)
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(limit)
            .offset(offset)
        )
        records = result.scalars().all()
        return [self._to_info(record) for record in records], int(total or 0)

    async def get_for_update(self, user_id: UUID) -> User | None:
        result = await self._session.execute(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def count_active_owners(self) -> int:
        result = await self._session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "owner", User.is_active.is_(True))
        )
        return int(result or 0)

    async def create_admin(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
    ) -> AdminUserInfo:
        record = User(
            tenant_id=self._tenant_id(),
            email=email,
            name=name,
            role="admin",
            password_hash=password_hash,
            verification_status="approved",
            is_active=True,
            token_version=1,
        )
        self._session.add(record)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION:
                raise EmailTakenError("Email is already registered") from exc
            raise
        return self._to_info(record)

    async def deactivate(self, user_id: UUID, *, token_version: int) -> None:
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                is_active=False,
                token_version=token_version,
                updated_at=func.now(),
            )
        )

    async def revoke_all_sessions(self, user_id: UUID, *, revoked_at: datetime) -> None:
        await self._session.execute(
            update(RefreshSessionRecord)
            .where(
                RefreshSessionRecord.user_id == user_id,
                RefreshSessionRecord.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, updated_at=revoked_at)
        )

    @staticmethod
    def _to_info(record: User) -> AdminUserInfo:
        return AdminUserInfo(
            id=record.id,
            email=record.email,
            name=record.name,
            role=record.role,
            is_active=record.is_active,
            mfa_enabled=record.mfa_enabled,
            created_at=record.created_at,
        )
