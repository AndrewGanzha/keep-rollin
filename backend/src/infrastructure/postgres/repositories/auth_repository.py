from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from src.application.repositories.i_auth_repository import (
    IAuthRepository,
    MfaChallengeInfo,
    MfaState,
    PasswordResetInfo,
    RefreshSessionInfo,
)
from src.domain.entities.user_account import (
    EmailTakenError,
    UserAccount,
    UserRole,
    VerificationStatus,
)
from src.infrastructure.postgres.models.mfa_challenge_record import MfaChallengeRecord
from src.infrastructure.postgres.models.password_reset_token_record import (
    PasswordResetTokenRecord,
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

    async def get_by_email_for_update(self, email: str) -> UserAccount | None:
        result = await self._session.execute(
            select(User)
            .where(User.email == email)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = result.scalar_one_or_none()
        return None if record is None else self._to_domain(record)

    async def get_by_id_for_update(self, user_id: UUID) -> UserAccount | None:
        result = await self._session.execute(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = result.scalar_one_or_none()
        return None if record is None else self._to_domain(record)

    async def get_mfa_state(self, user_id: UUID) -> MfaState | None:
        result = await self._session.execute(
            select(
                User.mfa_enabled,
                User.mfa_secret_enc,
                User.mfa_last_step,
                User.mfa_failed_attempts,
                User.mfa_failure_window_started_at,
                User.mfa_locked_until,
                User.mfa_recovery_hashes,
            ).where(User.id == user_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return MfaState(
            enabled=bool(row.mfa_enabled),
            secret_enc=row.mfa_secret_enc,
            last_step=row.mfa_last_step,
            failed_attempts=row.mfa_failed_attempts,
            failure_window_started_at=row.mfa_failure_window_started_at,
            locked_until=row.mfa_locked_until,
            recovery_hashes=tuple(row.mfa_recovery_hashes or ()),
        )

    async def create_mfa_challenge(
        self,
        *,
        jti: UUID,
        user_id: UUID,
        purpose: str,
        expires_at: datetime,
        secret_enc: str | None = None,
    ) -> None:
        self._session.add(
            MfaChallengeRecord(
                jti=jti,
                tenant_id=self._tenant_id(),
                user_id=user_id,
                purpose=purpose,
                secret_enc=secret_enc,
                expires_at=expires_at,
            )
        )
        await self._session.flush()

    async def get_mfa_challenge_for_update(self, jti: UUID) -> MfaChallengeInfo | None:
        result = await self._session.execute(
            select(MfaChallengeRecord).where(MfaChallengeRecord.jti == jti).with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return MfaChallengeInfo(
            jti=record.jti,
            user_id=record.user_id,
            purpose=record.purpose,
            secret_enc=record.secret_enc,
            expires_at=record.expires_at,
            consumed_at=record.consumed_at,
        )

    async def set_mfa_challenge_secret(self, jti: UUID, secret_enc: str) -> None:
        await self._session.execute(
            update(MfaChallengeRecord)
            .where(MfaChallengeRecord.jti == jti)
            .values(secret_enc=secret_enc)
        )

    async def consume_mfa_challenge(self, jti: UUID, *, consumed_at: datetime) -> None:
        await self._session.execute(
            update(MfaChallengeRecord)
            .where(
                MfaChallengeRecord.jti == jti,
                MfaChallengeRecord.consumed_at.is_(None),
            )
            .values(consumed_at=consumed_at)
        )

    async def enable_mfa(
        self,
        user_id: UUID,
        *,
        secret_enc: str,
        last_step: int,
        recovery_hashes: tuple[str, ...],
        token_version: int,
    ) -> None:
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                mfa_enabled=True,
                mfa_secret_enc=secret_enc,
                mfa_last_step=last_step,
                mfa_failed_attempts=0,
                mfa_failure_window_started_at=None,
                mfa_locked_until=None,
                mfa_recovery_hashes=list(recovery_hashes),
                token_version=token_version,
                updated_at=func.now(),
            )
        )

    async def update_mfa_attempt(
        self,
        user_id: UUID,
        *,
        last_step: int | None = None,
        failed_attempts: int | None = None,
        failure_window_started_at: datetime | None = None,
        locked_until: datetime | None = None,
        recovery_hashes: tuple[str, ...] | None = None,
    ) -> None:
        values: dict[str, object] = {"updated_at": func.now()}
        if last_step is not None:
            values["mfa_last_step"] = last_step
        if failed_attempts is not None:
            values["mfa_failed_attempts"] = failed_attempts
        if failure_window_started_at is not None:
            values["mfa_failure_window_started_at"] = failure_window_started_at
        if locked_until is not None:
            values["mfa_locked_until"] = locked_until
        if recovery_hashes is not None:
            values["mfa_recovery_hashes"] = list(recovery_hashes)
        await self._session.execute(update(User).where(User.id == user_id).values(**values))

    async def reset_mfa_attempts(
        self,
        user_id: UUID,
        *,
        last_step: int | None = None,
        recovery_hashes: tuple[str, ...] | None = None,
    ) -> None:
        values: dict[str, object] = {
            "mfa_failed_attempts": 0,
            "mfa_failure_window_started_at": None,
            "mfa_locked_until": None,
            "updated_at": func.now(),
        }
        if last_step is not None:
            values["mfa_last_step"] = last_step
        if recovery_hashes is not None:
            values["mfa_recovery_hashes"] = list(recovery_hashes)
        await self._session.execute(update(User).where(User.id == user_id).values(**values))

    async def create_password_reset_token(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        token_secret_enc: str,
        expires_at: datetime,
    ) -> UUID:
        record = PasswordResetTokenRecord(
            tenant_id=self._tenant_id(),
            user_id=user_id,
            token_hash=token_hash,
            token_secret_enc=token_secret_enc,
            expires_at=expires_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record.id

    async def get_password_reset_for_update(self, token_hash: str) -> PasswordResetInfo | None:
        result = await self._session.execute(
            select(PasswordResetTokenRecord)
            .where(PasswordResetTokenRecord.token_hash == token_hash)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        record = result.scalar_one_or_none()
        return self._reset_info(record)

    async def get_password_reset(self, token_hash: str) -> PasswordResetInfo | None:
        result = await self._session.execute(
            select(PasswordResetTokenRecord).where(
                PasswordResetTokenRecord.token_hash == token_hash
            )
        )
        return self._reset_info(result.scalar_one_or_none())

    @staticmethod
    def _reset_info(record: PasswordResetTokenRecord | None) -> PasswordResetInfo | None:
        if record is None:
            return None
        return PasswordResetInfo(
            id=record.id,
            user_id=record.user_id,
            expires_at=record.expires_at,
            consumed_at=record.consumed_at,
            token_secret_enc=record.token_secret_enc,
        )

    async def consume_password_reset(
        self,
        token_id: UUID,
        *,
        user_id: UUID,
        consumed_at: datetime,
    ) -> None:
        await self._session.execute(
            update(PasswordResetTokenRecord)
            .where(
                PasswordResetTokenRecord.id == token_id,
                PasswordResetTokenRecord.user_id == user_id,
                PasswordResetTokenRecord.consumed_at.is_(None),
            )
            .values(consumed_at=consumed_at)
        )
        await self._session.execute(
            update(PasswordResetTokenRecord)
            .where(
                PasswordResetTokenRecord.user_id == user_id,
                PasswordResetTokenRecord.consumed_at.is_(None),
            )
            .values(consumed_at=consumed_at)
        )

    async def update_password(
        self,
        user_id: UUID,
        *,
        password_hash: str,
        token_version: int,
    ) -> None:
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                password_hash=password_hash,
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
