from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.domain.entities.user_account import UserAccount


@dataclass(frozen=True)
class RefreshSessionInfo:
    id: UUID
    user_id: UUID
    family_id: UUID
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class MfaState:
    enabled: bool
    secret_enc: str | None
    last_step: int | None
    failed_attempts: int
    failure_window_started_at: datetime | None
    locked_until: datetime | None
    recovery_hashes: tuple[str, ...]


@dataclass(frozen=True)
class MfaChallengeInfo:
    jti: UUID
    user_id: UUID
    purpose: str
    secret_enc: str | None
    expires_at: datetime
    consumed_at: datetime | None


@dataclass(frozen=True)
class PasswordResetInfo:
    id: UUID
    user_id: UUID
    expires_at: datetime
    consumed_at: datetime | None
    token_secret_enc: str | None


class IAuthRepository(ABC):
    @abstractmethod
    async def get_by_email(self, email: str) -> UserAccount | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> UserAccount | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_email_for_update(self, email: str) -> UserAccount | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id_for_update(self, user_id: UUID) -> UserAccount | None:
        raise NotImplementedError

    @abstractmethod
    async def get_mfa_state(self, user_id: UUID) -> MfaState | None:
        raise NotImplementedError

    @abstractmethod
    async def create_mfa_challenge(
        self,
        *,
        jti: UUID,
        user_id: UUID,
        purpose: str,
        expires_at: datetime,
        secret_enc: str | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_mfa_challenge_for_update(self, jti: UUID) -> MfaChallengeInfo | None:
        raise NotImplementedError

    @abstractmethod
    async def set_mfa_challenge_secret(self, jti: UUID, secret_enc: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def consume_mfa_challenge(self, jti: UUID, *, consumed_at: datetime) -> None:
        raise NotImplementedError

    @abstractmethod
    async def enable_mfa(
        self,
        user_id: UUID,
        *,
        secret_enc: str,
        last_step: int,
        recovery_hashes: tuple[str, ...],
        token_version: int,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def reset_mfa_attempts(
        self,
        user_id: UUID,
        *,
        last_step: int | None = None,
        recovery_hashes: tuple[str, ...] | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def create_password_reset_token(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        token_secret_enc: str,
        expires_at: datetime,
    ) -> UUID:
        raise NotImplementedError

    @abstractmethod
    async def get_password_reset_for_update(self, token_hash: str) -> PasswordResetInfo | None:
        raise NotImplementedError

    @abstractmethod
    async def get_password_reset(self, token_hash: str) -> PasswordResetInfo | None:
        raise NotImplementedError

    @abstractmethod
    async def consume_password_reset(
        self,
        token_id: UUID,
        *,
        user_id: UUID,
        consumed_at: datetime,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update_password(
        self,
        user_id: UUID,
        *,
        password_hash: str,
        token_version: int,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def revoke_all_sessions(self, user_id: UUID, *, revoked_at: datetime) -> None:
        raise NotImplementedError

    @abstractmethod
    async def create_user(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
        phone: str | None,
    ) -> UserAccount:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def get_refresh_session(self, token_hash: str) -> RefreshSessionInfo | None:
        raise NotImplementedError

    @abstractmethod
    async def get_refresh_session_for_update(self, token_hash: str) -> RefreshSessionInfo | None:
        raise NotImplementedError

    @abstractmethod
    async def lock_family(self, family_id: UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    async def revoke_session(
        self,
        session_id: UUID,
        *,
        revoked_at: datetime,
        replaced_by_id: UUID | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def revoke_family(self, family_id: UUID, *, revoked_at: datetime) -> None:
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        raise NotImplementedError
