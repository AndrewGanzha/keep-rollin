from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from src.application.repositories.i_auth_repository import IAuthRepository, RefreshSessionInfo
from src.domain.entities.user_account import (
    EmailTakenError,
    UserAccount,
    UserRole,
    VerificationStatus,
)
from src.infrastructure.postgres.models.refresh_session_record import RefreshSessionRecord

UNIQUE_VIOLATION = "23505"


class AuthRepository(IAuthRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _tenant_id(self) -> UUID:
        value = self._session.info.get("tenant_id")
        if not value:
            raise RuntimeError("tenant context is missing")
        return UUID(str(value))

    async def get_by_email(self, email: str) -> UserAccount | None:
        result = await self._session.execute(select(User).where(User.email == email))
        record = result.scalar_one_or_none()
        return None if record is None else self._to_domain(record)

    async def get_by_id(self, user_id: UUID) -> UserAccount | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        record = result.scalar_one_or_none()
        return None if record is None else self._to_domain(record)

    async def create_user(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
        phone: str | None,
    ) -> UserAccount:
        record = User(
            tenant_id=self._tenant_id(),
            email=email,
            phone=phone,
            name=name,
            role="user",
            password_hash=password_hash,
            verification_status="pending",
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
        return self._to_domain(record)

    async def create_refresh_session(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        family_id: UUID,
        expires_at: datetime,
        user_agent: str | None,
        ip: str | None,
    ) -> UUID:
        record = RefreshSessionRecord(
            tenant_id=self._tenant_id(),
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )
        self._session.add(record)
        await self._session.flush()
        return record.id

    async def get_refresh_session(self, token_hash: str) -> RefreshSessionInfo | None:
        result = await self._session.execute(
            select(RefreshSessionRecord).where(RefreshSessionRecord.token_hash == token_hash)
        )
        return self._refresh_info(result.scalar_one_or_none())

    async def get_refresh_session_for_update(self, token_hash: str) -> RefreshSessionInfo | None:
        result = await self._session.execute(
            select(RefreshSessionRecord)
            .where(RefreshSessionRecord.token_hash == token_hash)
            .with_for_update()
        )
        return self._refresh_info(result.scalar_one_or_none())

    async def lock_family(self, family_id: UUID) -> None:
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(str(family_id), 0)))
        )

    @staticmethod
    def _refresh_info(record: RefreshSessionRecord | None) -> RefreshSessionInfo | None:
        if record is None:
            return None
        return RefreshSessionInfo(
            id=record.id,
            user_id=record.user_id,
            family_id=record.family_id,
            expires_at=record.expires_at,
            revoked_at=record.revoked_at,
        )

    async def revoke_session(
        self,
        session_id: UUID,
        *,
        revoked_at: datetime,
        replaced_by_id: UUID | None = None,
    ) -> None:
        values: dict[str, object] = {
            "revoked_at": revoked_at,
            "updated_at": revoked_at,
        }
        if replaced_by_id is not None:
            values["replaced_by_id"] = replaced_by_id
        await self._session.execute(
            update(RefreshSessionRecord)
            .where(
                RefreshSessionRecord.id == session_id,
                RefreshSessionRecord.revoked_at.is_(None),
            )
            .values(**values)
        )

    async def revoke_family(self, family_id: UUID, *, revoked_at: datetime) -> None:
        await self._session.execute(
            update(RefreshSessionRecord)
            .where(
                RefreshSessionRecord.family_id == family_id,
                RefreshSessionRecord.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, updated_at=revoked_at)
        )

    async def commit(self) -> None:
        await self._session.commit()

    @staticmethod
    def _to_domain(record: User) -> UserAccount:
        display_name = (record.name or "").strip() or record.email.split("@", 1)[0]
        return UserAccount(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            email=record.email,
            name=display_name[:120] or "user",
            role=cast(UserRole, record.role),
            verification_status=cast(VerificationStatus, record.verification_status),
            is_active=record.is_active,
            password_hash=record.password_hash,
            token_version=record.token_version,
            phone=record.phone,
        )
