from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated, cast
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from src.application.dtos.auth_dto import LoginRequest
from src.application.services.auth import AuthService, TokenService
from src.application.services.outbox import OutboxWriter
from src.application.services.rate_limit import SlidingWindowRateLimiter
from src.domain.entities.user_account import (
    InactiveUserError,
    InvalidTokenError,
    TenantMismatchError,
    TokenExpiredError,
    UserAccount,
)
from src.infrastructure.postgres.repositories.auth_repository import AuthRepository
from src.infrastructure.postgres.repositories.outbox_repository import OutboxRepository
from src.infrastructure.security.password_hasher import Argon2PasswordHasher
from src.infrastructure.security.secret_box import CodeHasher, SecretBox
from src.infrastructure.security.token_service import JwtTokenService

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_password_hasher() -> Argon2PasswordHasher:
    """Return the process-wide hasher with its precomputed dummy hash."""
    return Argon2PasswordHasher()


def get_auth_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthService:
    settings = request.app.state.settings
    tenant_id = cast(UUID | None, getattr(request.state, "tenant_id", None))
    if tenant_id is None:
        raise HTTPException(status_code=404, detail={"code": "tenant_not_found"})
    secret_box = cast(SecretBox | None, getattr(request.app.state, "secret_box", None))
    code_hasher = cast(CodeHasher | None, getattr(request.app.state, "code_hasher", None))
    if secret_box is None or code_hasher is None:
        raise HTTPException(status_code=503, detail={"code": "service_unavailable"})
    return AuthService(
        AuthRepository(session),
        get_password_hasher(),
        cast(
            TokenService,
            JwtTokenService(
                secret=settings.jwt_secret,
                access_ttl_seconds=settings.access_ttl_seconds,
                mfa_ttl_seconds=300,
            ),
        ),
        refresh_ttl_days=settings.refresh_ttl_days,
        tenant_id=tenant_id,
        password_work_timeout_seconds=settings.password_work_timeout_seconds,
        secret_box=secret_box,
        code_hasher=code_hasher,
        issuer=settings.app_name,
        outbox=OutboxWriter(OutboxRepository(session)),
        password_reset_ttl_seconds=settings.password_reset_ttl_seconds,
    )


def _unauthorized(code: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": code},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    service: Annotated[AuthService, Depends(get_auth_service)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> UserAccount:
    if credentials is None:
        raise _unauthorized("token_invalid")
    try:
        return await service.authenticate_access(access_token=credentials.credentials)
    except TenantMismatchError as exc:
        raise HTTPException(status_code=403, detail={"code": "tenant_mismatch"}) from exc
    except InactiveUserError as exc:
        raise HTTPException(status_code=403, detail={"code": "forbidden_role"}) from exc
    except TokenExpiredError as exc:
        raise _unauthorized("token_expired") from exc
    except InvalidTokenError as exc:
        raise _unauthorized("token_invalid") from exc


def require_permission(
    permission: str,
) -> Callable[[UserAccount], Awaitable[UserAccount]]:
    async def dependency(
        user: Annotated[UserAccount, Depends(get_current_user)],
    ) -> UserAccount:
        if permission not in user.permissions:
            raise HTTPException(status_code=403, detail={"code": "forbidden_role"})
        return user

    return dependency


def _origin_matches_request(request: Request, origin: str) -> bool:
    if origin != origin.strip():
        return False
    try:
        parsed = urlsplit(origin)
        authority = urlsplit(f"//{request.headers.get('host', '')}")
    except ValueError:
        return False
    if (
        parsed.scheme not in ("http", "https")
        or parsed.scheme != request.url.scheme
        or "@" in parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or origin != f"{parsed.scheme}://{parsed.netloc}"
        or not parsed.hostname
        or not authority.hostname
        or "@" in authority.netloc
        or authority.username is not None
        or authority.password is not None
    ):
        return False
    default_port = 443 if parsed.scheme == "https" else 80
    try:
        origin_port = parsed.port if parsed.port is not None else default_port
        request_port = authority.port if authority.port is not None else default_port
    except ValueError:
        return False
    if origin_port == 0 or request_port == 0:
        return False
    return (
        parsed.hostname.casefold() == authority.hostname.casefold() and origin_port == request_port
    )


async def verify_csrf(request: Request) -> None:
    origins = request.headers.getlist("origin")
    sec_fetch_site = request.headers.get("sec-fetch-site")
    if len(origins) != 1:
        raise HTTPException(status_code=403, detail={"code": "forbidden_role"})
    if sec_fetch_site not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail={"code": "forbidden_role"})
    origin = origins[0]
    if not _origin_matches_request(request, origin):
        raise HTTPException(status_code=403, detail={"code": "forbidden_role"})


def _rate_limit_error(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={"code": "rate_limited"},
        headers={
            "Retry-After": str(retry_after),
            "Cache-Control": "no-store",
        },
    )


async def enforce_login_rate_limit(
    request: Request,
    payload: LoginRequest,
) -> None:
    ip_limiter = cast(
        SlidingWindowRateLimiter | None,
        getattr(request.app.state, "login_ip_limiter", None),
    )
    email_limiter = cast(
        SlidingWindowRateLimiter | None,
        getattr(request.app.state, "login_email_limiter", None),
    )
    if ip_limiter is None or email_limiter is None:
        return
    tenant_id = str(getattr(request.state, "tenant_id", "unknown"))
    ip = request.client.host if request.client else "unknown"
    retry_after = ip_limiter.hit(f"{tenant_id}:{ip}")
    if retry_after is not None:
        raise _rate_limit_error(retry_after)
    retry_after = email_limiter.hit(f"{tenant_id}:{payload.email}")
    if retry_after is not None:
        raise _rate_limit_error(retry_after)
