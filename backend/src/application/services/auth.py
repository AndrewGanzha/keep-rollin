import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from src.application.repositories.i_auth_repository import IAuthRepository
from src.application.services.password_executor import run_password_work
from src.domain.entities.user_account import (
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    SessionRevokedError,
    TenantMismatchError,
    UserAccount,
    UserRole,
)
from src.domain.policies.password_policy import ensure_password_not_compromised


@dataclass(frozen=True)
class AccessClaims:
    sub: UUID
    tnt: UUID
    role: UserRole
    ver: int
    jti: str


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def verify_dummy(self, password: str) -> None: ...


class TokenService(Protocol):
    @property
    def expires_in(self) -> int: ...

    def create_access(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        role: UserRole,
        token_version: int,
    ) -> str: ...

    def decode_access(self, token: str) -> AccessClaims: ...


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    user: UserAccount


def hash_refresh_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(
        self,
        repository: IAuthRepository,
        password_hasher: PasswordHasher,
        token_service: TokenService,
        *,
        refresh_ttl_days: int,
        tenant_id: UUID,
        password_work_timeout_seconds: float = 5.0,
    ) -> None:
        self._repository = repository
        self._password_hasher = password_hasher
        self._token_service = token_service
        self._refresh_ttl_days = refresh_ttl_days
        self._tenant_id = tenant_id
        self._password_work_timeout_seconds = password_work_timeout_seconds

    async def register(
        self,
        *,
        email: str,
        password: str,
        name: str | None = None,
        phone: str | None = None,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> IssuedTokens:
        normalized = email.strip().lower()
        ensure_password_not_compromised(password)
        password_hash = await run_password_work(
            lambda: self._password_hasher.hash(password),
            timeout_seconds=self._password_work_timeout_seconds,
        )
        resolved_name = (name or "").strip() or normalized.split("@", 1)[0]
        user = await self._repository.create_user(
            email=normalized,
            name=resolved_name[:120],
            password_hash=password_hash,
            phone=phone,
        )
        return await self._issue(user, user_agent=user_agent, ip=ip)

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> IssuedTokens:
        user = await self._repository.get_by_email(email.strip().lower())
        await self._repository.commit()
        if user is None or user.password_hash is None:
            await run_password_work(
                lambda: self._password_hasher.verify_dummy(password),
                timeout_seconds=self._password_work_timeout_seconds,
            )
            raise InvalidCredentialsError("Invalid email or password")
        password_hash = user.password_hash
        verified = await run_password_work(
            lambda: self._password_hasher.verify(password_hash, password),
            timeout_seconds=self._password_work_timeout_seconds,
        )
        if not verified:
            raise InvalidCredentialsError("Invalid email or password")
        if not user.is_active:
            raise InactiveUserError("User is inactive")
        return await self._issue(user, user_agent=user_agent, ip=ip)

    async def refresh(
        self,
        *,
        refresh_token: str,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> IssuedTokens:
        token_hash = hash_refresh_token(refresh_token)
        session = await self._repository.get_refresh_session(token_hash)
        if session is None:
            raise InvalidTokenError("Refresh session not found")
        await self._repository.lock_family(session.family_id)
        session = await self._repository.get_refresh_session_for_update(token_hash)
        if session is None:
            raise InvalidTokenError("Refresh session not found")
        now = datetime.now(UTC)
        if session.expires_at <= now:
            await self._repository.revoke_session(session.id, revoked_at=now)
            await self._repository.commit()
            raise InvalidTokenError("Refresh session expired")
        if session.revoked_at is not None:
            await self._repository.revoke_family(session.family_id, revoked_at=now)
            await self._repository.commit()
            raise SessionRevokedError("Refresh session was already used")

        user = await self._repository.get_by_id(session.user_id)
        if user is None or not user.is_active:
            await self._repository.revoke_family(session.family_id, revoked_at=now)
            await self._repository.commit()
            raise SessionRevokedError("User session is not active")

        new_token = secrets.token_urlsafe(48)
        new_session_id = await self._repository.create_refresh_session(
            user_id=user.id,
            token_hash=hash_refresh_token(new_token),
            family_id=session.family_id,
            expires_at=now + timedelta(days=self._refresh_ttl_days),
            user_agent=user_agent,
            ip=ip,
        )
        await self._repository.revoke_session(
            session.id,
            revoked_at=now,
            replaced_by_id=new_session_id,
        )
        return IssuedTokens(
            access_token=self._token_service.create_access(
                user_id=user.id,
                tenant_id=self._tenant_id,
                role=user.role,
                token_version=user.token_version,
            ),
            refresh_token=new_token,
            expires_in=self._token_service.expires_in,
            user=user,
        )

    async def logout(self, *, refresh_token: str) -> None:
        session = await self._repository.get_refresh_session(hash_refresh_token(refresh_token))
        if session is None:
            return
        await self._repository.lock_family(session.family_id)
        current = await self._repository.get_refresh_session(hash_refresh_token(refresh_token))
        if current is None:
            return
        now = datetime.now(UTC)
        if current.expires_at <= now:
            if current.revoked_at is None:
                await self._repository.revoke_session(current.id, revoked_at=now)
                await self._repository.commit()
            return
        await self._repository.revoke_family(current.family_id, revoked_at=now)
        await self._repository.commit()

    async def authenticate_access(self, *, access_token: str) -> UserAccount:
        claims = self._token_service.decode_access(access_token)
        if claims.tnt != self._tenant_id:
            raise TenantMismatchError("Access token tenant does not match request host")
        user = await self._repository.get_by_id(claims.sub)
        if user is None or not user.is_active:
            raise InactiveUserError("User is inactive")
        if user.token_version != claims.ver:
            raise InvalidTokenError("Access token version is stale")
        return user

    async def _issue(
        self,
        user: UserAccount,
        *,
        user_agent: str | None,
        ip: str | None,
    ) -> IssuedTokens:
        now = datetime.now(UTC)
        refresh_token = secrets.token_urlsafe(48)
        await self._repository.create_refresh_session(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            family_id=uuid4(),
            expires_at=now + timedelta(days=self._refresh_ttl_days),
            user_agent=user_agent,
            ip=ip,
        )
        return IssuedTokens(
            access_token=self._token_service.create_access(
                user_id=user.id,
                tenant_id=self._tenant_id,
                role=user.role,
                token_version=user.token_version,
            ),
            refresh_token=refresh_token,
            expires_in=self._token_service.expires_in,
            user=user,
        )
