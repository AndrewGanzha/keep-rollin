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


class IAuthRepository(ABC):
    @abstractmethod
    async def get_by_email(self, email: str) -> UserAccount | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> UserAccount | None:
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
