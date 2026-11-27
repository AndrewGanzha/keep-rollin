import hashlib
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, NoReturn, Protocol
from uuid import UUID, uuid4

from src.application.repositories.i_auth_repository import (
    IAuthRepository,
    MfaChallengeInfo,
    MfaState,
)
from src.application.services.outbox import OutboxWriter
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
from src.infrastructure.security.mfa_codes import (
    generate_recovery_codes,
    normalize_recovery_code,
)
from src.infrastructure.security.secret_box import CodeHasher, SecretBox
from src.infrastructure.security.totp import (
    build_otpauth_uri,
    generate_secret,
    verify_code,
)

MFA_TTL_SECONDS = 300
MFA_MAX_FAILURES = 5
MFA_LOCKOUT_SECONDS = 300
MFA_FAILURE_WINDOW_SECONDS = 300
PASSWORD_RESET_TTL_SECONDS = 3600
STAFF_ROLES = ("owner", "admin")

MfaPurpose = Literal["login", "enroll"]


@dataclass(frozen=True)
class AccessClaims:
    sub: UUID
    tnt: UUID
    role: UserRole
    ver: int
    jti: str


class MfaClaims(Protocol):
    sub: UUID
    tnt: UUID
    ver: int
    jti: UUID
    purpose: MfaPurpose


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def verify_dummy(self, password: str) -> None: ...


class TokenService(Protocol):
    @property
    def expires_in(self) -> int: ...

    @property
    def mfa_expires_in(self) -> int: ...

    def create_access(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        role: UserRole,
        token_version: int,
    ) -> str: ...

    def decode_access(self, token: str) -> AccessClaims: ...

    def create_mfa(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        token_version: int,
        jti: UUID,
        purpose: MfaPurpose,
    ) -> str: ...

    def decode_mfa(self, token: str) -> MfaClaims: ...


class MfaError(Exception):
    pass


class InvalidMfaChallengeError(InvalidTokenError):
    pass


class InvalidMfaCodeError(MfaError):
    pass


class MfaLockedError(MfaError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("MFA verification is locked")
        self.retry_after = retry_after


class MfaAlreadyEnabledError(MfaError):
    pass


class InvalidPasswordResetError(Exception):
    pass


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    user: UserAccount


@dataclass(frozen=True)
class MfaChallenge:
    mfa_token: str
    purpose: MfaPurpose
    expires_in: int


@dataclass(frozen=True)
class MfaSetup:
    secret: str
    otpauth_uri: str


@dataclass(frozen=True)
class MfaConfirmation:
    tokens: IssuedTokens
    recovery_codes: tuple[str, ...]


def hash_refresh_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_reset_token(value: str) -> str:
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
        secret_box: SecretBox,
        code_hasher: CodeHasher,
        issuer: str = "Keep Rollin",
        outbox: OutboxWriter | None = None,
        password_reset_ttl_seconds: int = PASSWORD_RESET_TTL_SECONDS,
    ) -> None:
        self._repository = repository
        self._password_hasher = password_hasher
        self._token_service = token_service
        self._refresh_ttl_days = refresh_ttl_days
        self._tenant_id = tenant_id
        self._password_work_timeout_seconds = password_work_timeout_seconds
        self._secret_box = secret_box
        self._code_hasher = code_hasher
        self._issuer = issuer
        self._outbox = outbox
        self._password_reset_ttl_seconds = password_reset_ttl_seconds

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
    ) -> IssuedTokens | MfaChallenge:
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
        original_version = user.token_version
        user = await self._repository.get_by_id_for_update(user.id)
        if (
            user is None
            or not user.is_active
            or user.password_hash != password_hash
            or user.token_version != original_version
        ):
            raise InvalidCredentialsError("Invalid email or password")
        if user.role in STAFF_ROLES:
            state = await self._repository.get_mfa_state(user.id)
            purpose: MfaPurpose = "login" if state and state.enabled else "enroll"
            return await self._create_mfa_challenge(user, purpose=purpose)
        return await self._issue(user, user_agent=user_agent, ip=ip)

    async def setup_mfa(self, *, mfa_token: str) -> MfaSetup:
        claims = self._token_service.decode_mfa(mfa_token)
        self._check_tenant(claims.tnt)
        if claims.purpose != "enroll":
            raise InvalidMfaChallengeError("MFA enrollment challenge is required")
        user = await self._repository.get_by_id_for_update(claims.sub)
        if user is None or not user.is_active or user.token_version != claims.ver:
            raise InvalidMfaChallengeError("MFA challenge is no longer valid")
        challenge = await self._repository.get_mfa_challenge_for_update(claims.jti)
        self._validate_challenge(challenge, user=user, purpose="enroll")
        state = await self._repository.get_mfa_state(user.id)
        if state is not None and state.enabled:
            raise MfaAlreadyEnabledError("MFA is already enabled")
        secret = generate_secret()
        secret_enc = self._secret_box.encrypt(
            secret,
            context=self._mfa_context(user.id),
        )
        await self._repository.set_mfa_challenge_secret(claims.jti, secret_enc)
        return MfaSetup(
            secret=secret,
            otpauth_uri=build_otpauth_uri(
                secret=secret,
                account=user.email,
                issuer=self._issuer,
            ),
        )

    async def confirm_mfa(
        self,
        *,
        mfa_token: str,
        code: str,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> MfaConfirmation:
        claims = self._token_service.decode_mfa(mfa_token)
        self._check_tenant(claims.tnt)
        if claims.purpose != "enroll":
            raise InvalidMfaChallengeError("MFA enrollment challenge is required")
        user = await self._repository.get_by_id_for_update(claims.sub)
        if user is None or not user.is_active or user.token_version != claims.ver:
            raise InvalidMfaChallengeError("MFA challenge is no longer valid")
        challenge = await self._repository.get_mfa_challenge_for_update(claims.jti)
        self._validate_challenge(challenge, user=user, purpose="enroll")
        state = await self._repository.get_mfa_state(user.id)
        if state is not None and state.enabled:
            raise MfaAlreadyEnabledError("MFA is already enabled")
        if challenge is None or challenge.secret_enc is None:
            raise InvalidMfaChallengeError("MFA setup has not been started")
        self._ensure_unlocked(state)
        secret = self._secret_box.decrypt(
            challenge.secret_enc,
            context=self._mfa_context(user.id),
        )
        step = verify_code(secret, code)
        if step is None:
            await self._record_mfa_failure(user.id, state)
        assert step is not None
        recovery_codes = generate_recovery_codes()
        recovery_hashes = tuple(
            self._code_hasher.hash(normalize_recovery_code(code)) for code in recovery_codes
        )
        await self._repository.enable_mfa(
            user.id,
            secret_enc=challenge.secret_enc,
            last_step=step,
            recovery_hashes=recovery_hashes,
            token_version=user.token_version + 1,
        )
        await self._repository.revoke_all_sessions(user.id, revoked_at=datetime.now(UTC))
        await self._repository.consume_mfa_challenge(claims.jti, consumed_at=datetime.now(UTC))
        refreshed = await self._repository.get_by_id(user.id)
        if refreshed is None:
            raise InvalidMfaChallengeError("User is no longer available")
        return MfaConfirmation(
            tokens=await self._issue(refreshed, user_agent=user_agent, ip=ip),
            recovery_codes=tuple(recovery_codes),
        )

    async def verify_mfa(
        self,
        *,
        mfa_token: str,
        code: str,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> IssuedTokens:
        claims = self._token_service.decode_mfa(mfa_token)
        self._check_tenant(claims.tnt)
        if claims.purpose != "login":
            raise InvalidMfaChallengeError("MFA login challenge is required")
        user = await self._repository.get_by_id_for_update(claims.sub)
        if user is None or not user.is_active or user.token_version != claims.ver:
            raise InvalidMfaChallengeError("MFA challenge is no longer valid")
        challenge = await self._repository.get_mfa_challenge_for_update(claims.jti)
        self._validate_challenge(challenge, user=user, purpose="login")
        state = await self._repository.get_mfa_state(user.id)
        if state is None or not state.enabled or state.secret_enc is None:
            raise InvalidMfaChallengeError("MFA is not enabled for this account")
        self._ensure_unlocked(state)
        secret = self._secret_box.decrypt(
            state.secret_enc,
            context=self._mfa_context(user.id),
        )
        now = datetime.now(UTC)
        step = verify_code(secret, code, last_step=state.last_step)
        if step is not None:
            await self._repository.reset_mfa_attempts(user.id, last_step=step)
        else:
            recovery_hash = self._match_recovery_code(state, code)
            if recovery_hash is None:
                await self._record_mfa_failure(user.id, state)
            remaining = tuple(hash for hash in state.recovery_hashes if hash != recovery_hash)
            await self._repository.reset_mfa_attempts(user.id, recovery_hashes=remaining)
        await self._repository.consume_mfa_challenge(claims.jti, consumed_at=now)
        refreshed = await self._repository.get_by_id(user.id)
        if refreshed is None:
            raise InvalidMfaChallengeError("User is no longer available")
        return await self._issue(refreshed, user_agent=user_agent, ip=ip)

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
        user = await self._repository.get_by_id_for_update(session.user_id)
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
        if user is None or not user.is_active:
            await self._repository.revoke_family(session.family_id, revoked_at=now)
            await self._repository.commit()
            raise SessionRevokedError("User session is not active")
        if user.role in STAFF_ROLES:
            state = await self._repository.get_mfa_state(user.id)
            if state is None or not state.enabled:
                await self._repository.revoke_family(session.family_id, revoked_at=now)
                await self._repository.commit()
                raise InvalidTokenError("Staff MFA is not enabled")

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
        self._check_tenant(claims.tnt)
        user = await self._repository.get_by_id(claims.sub)
        if user is None or not user.is_active:
            raise InactiveUserError("User is inactive")
        if user.token_version != claims.ver:
            raise InvalidTokenError("Access token version is stale")
        if user.role in STAFF_ROLES:
            state = await self._repository.get_mfa_state(user.id)
            if state is None or not state.enabled:
                raise InvalidTokenError("Staff MFA is not enabled")
        return user

    async def mfa_enabled(self, user_id: UUID) -> bool:
        state = await self._repository.get_mfa_state(user_id)
        return bool(state and state.enabled)

    async def verify_step_up(self, *, user_id: UUID, code: str | None) -> None:
        """Verify a fresh TOTP for an already-authenticated staff actor."""
        user = await self._repository.get_by_id_for_update(user_id)
        if user is None or not user.is_active:
            raise InactiveUserError("User is inactive")
        state = await self._repository.get_mfa_state(user.id)
        if state is None or not state.enabled or state.secret_enc is None:
            raise InvalidMfaCodeError("MFA is not enabled")
        self._ensure_unlocked(state)
        if not code:
            await self._record_mfa_failure(user.id, state)
        assert code is not None
        secret = self._secret_box.decrypt(
            state.secret_enc,
            context=self._mfa_context(user.id),
        )
        step = verify_code(secret, code, last_step=state.last_step)
        if step is None:
            await self._record_mfa_failure(user.id, state)
        await self._repository.reset_mfa_attempts(user.id, last_step=step)

    async def ensure_step_up_available(self, *, user_id: UUID) -> None:
        """Reject a locked or non-MFA actor before expensive password work."""
        state = await self._repository.get_mfa_state(user_id)
        if state is None or not state.enabled:
            raise InvalidMfaCodeError("MFA is not enabled")
        self._ensure_unlocked(state)

    async def request_password_reset(self, *, email: str) -> None:
        user = await self._repository.get_by_email(email.strip().lower())
        if user is None or not user.is_active or user.password_hash is None:
            return
        raw_token = secrets.token_urlsafe(32)
        token_id = await self._repository.create_password_reset_token(
            user_id=user.id,
            token_hash=hash_reset_token(raw_token),
            token_secret_enc=self._secret_box.encrypt(
                raw_token,
                context=self._reset_context(user.id),
            ),
            expires_at=datetime.now(UTC) + timedelta(seconds=self._password_reset_ttl_seconds),
        )
        if self._outbox is not None:
            await self._outbox.enqueue(
                event_type="auth.password_reset",
                entity_id=token_id,
                user_id=user.id,
                channel="email",
                payload={"reset_token_id": str(token_id)},
            )

    async def reset_password(self, *, token: str, password: str) -> None:
        ensure_password_not_compromised(password)
        reset = await self._repository.get_password_reset(hash_reset_token(token))
        now = datetime.now(UTC)
        if reset is None or reset.consumed_at is not None or reset.expires_at <= now:
            raise InvalidPasswordResetError("Password reset token is invalid")
        user = await self._repository.get_by_id_for_update(reset.user_id)
        if user is None or not user.is_active:
            raise InvalidPasswordResetError("Password reset token is invalid")
        reset = await self._repository.get_password_reset_for_update(hash_reset_token(token))
        if reset is None or reset.consumed_at is not None or reset.expires_at <= now:
            raise InvalidPasswordResetError("Password reset token is invalid")
        password_hash = await run_password_work(
            lambda: self._password_hasher.hash(password),
            timeout_seconds=self._password_work_timeout_seconds,
        )
        await self._repository.update_password(
            user.id,
            password_hash=password_hash,
            token_version=user.token_version + 1,
        )
        await self._repository.consume_password_reset(
            reset.id,
            user_id=user.id,
            consumed_at=now,
        )
        await self._repository.revoke_all_sessions(user.id, revoked_at=now)

    async def _create_mfa_challenge(
        self,
        user: UserAccount,
        *,
        purpose: MfaPurpose,
    ) -> MfaChallenge:
        jti = uuid4()
        await self._repository.create_mfa_challenge(
            jti=jti,
            user_id=user.id,
            purpose=purpose,
            expires_at=datetime.now(UTC) + timedelta(seconds=MFA_TTL_SECONDS),
        )
        return MfaChallenge(
            mfa_token=self._token_service.create_mfa(
                user_id=user.id,
                tenant_id=self._tenant_id,
                token_version=user.token_version,
                jti=jti,
                purpose=purpose,
            ),
            purpose=purpose,
            expires_in=self._token_service.mfa_expires_in,
        )

    def _validate_challenge(
        self,
        challenge: MfaChallengeInfo | None,
        *,
        user: UserAccount,
        purpose: MfaPurpose,
    ) -> None:
        if challenge is None:
            raise InvalidMfaChallengeError("MFA challenge was not found")
        now = datetime.now(UTC)
        if (
            challenge.user_id != user.id
            or challenge.purpose != purpose
            or challenge.consumed_at is not None
            or challenge.expires_at <= now
        ):
            raise InvalidMfaChallengeError("MFA challenge is no longer valid")

    def _ensure_unlocked(self, state: MfaState | None) -> None:
        if state is None or state.locked_until is None:
            return
        now = datetime.now(UTC)
        if state.locked_until > now:
            retry_after = max(1, math.ceil((state.locked_until - now).total_seconds()))
            raise MfaLockedError(retry_after)

    async def _record_mfa_failure(self, user_id: UUID, state: MfaState | None) -> NoReturn:
        now = datetime.now(UTC)
        window = state.failure_window_started_at if state is not None else None
        attempts = state.failed_attempts if state is not None else 0
        if window is None or (now - window).total_seconds() >= MFA_FAILURE_WINDOW_SECONDS:
            attempts = 1
            window = now
        else:
            attempts = min(attempts + 1, MFA_MAX_FAILURES)
        locked_until = (
            now + timedelta(seconds=MFA_LOCKOUT_SECONDS) if attempts >= MFA_MAX_FAILURES else None
        )
        await self._repository.update_mfa_attempt(
            user_id,
            failed_attempts=attempts,
            failure_window_started_at=window,
            locked_until=locked_until,
        )
        await self._repository.commit()
        raise InvalidMfaCodeError("Invalid MFA code")

    def _match_recovery_code(self, state: MfaState, code: str) -> str | None:
        try:
            normalized = normalize_recovery_code(code)
        except ValueError:
            return None
        candidate = self._code_hasher.hash(normalized)
        for stored in state.recovery_hashes:
            if secrets.compare_digest(stored, candidate):
                return stored
        return None

    def _mfa_context(self, user_id: UUID) -> str:
        return f"mfa:{self._tenant_id}:{user_id}"

    def _reset_context(self, user_id: UUID) -> str:
        return f"reset:{self._tenant_id}:{user_id}"

    def _check_tenant(self, tenant_id: UUID) -> None:
        if tenant_id != self._tenant_id:
            raise TenantMismatchError("Token tenant does not match request host")

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
