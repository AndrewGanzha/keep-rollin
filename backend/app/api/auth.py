from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import (
    enforce_login_rate_limit,
    get_auth_service,
    get_current_user,
    verify_csrf,
)
from app.api.deps import get_db_session
from src.application.dtos.auth_dto import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    MfaCodeRequest,
    MfaConfirmResponse,
    MfaSetupResponse,
    MfaTokenRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    RegisterRequest,
    SessionDTO,
    UserDTO,
)
from src.application.services.auth import (
    AuthService,
    InvalidMfaChallengeError,
    InvalidMfaCodeError,
    InvalidPasswordResetError,
    IssuedTokens,
    MfaAlreadyEnabledError,
    MfaChallenge,
    MfaLockedError,
)
from src.domain.entities.user_account import (
    AuthBusyError,
    EmailTakenError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    SessionRevokedError,
    TenantMismatchError,
    TokenExpiredError,
    UserAccount,
)
from src.domain.policies.password_policy import PasswordCompromisedError
from src.infrastructure.postgres.repositories.offer_repository import OfferRepository


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
    dependencies=[Depends(no_store)],
)


def _set_refresh_cookie(response: Response, request: Request, tokens: IssuedTokens) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=tokens.refresh_token,
        max_age=settings.refresh_ttl_days * 86400,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_refresh_cookie(response: Response, request: Request) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/",
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _login_response(tokens: IssuedTokens) -> LoginResponse:
    return LoginResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=UserDTO.from_domain(tokens.user),
        role=tokens.user.role,
        permissions=list(tokens.user.permissions),
    )


def _challenge_response(challenge: MfaChallenge) -> LoginResponse:
    return LoginResponse(
        expires_in=challenge.expires_in,
        mfa_required=challenge.purpose == "login",
        mfa_setup_required=challenge.purpose == "enroll",
        mfa_token=challenge.mfa_token,
    )


def _login_payload(
    result: IssuedTokens | MfaChallenge,
    response: Response,
    request: Request,
) -> LoginResponse:
    if isinstance(result, MfaChallenge):
        return _challenge_response(result)
    _set_refresh_cookie(response, request, result)
    return _login_response(result)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, PasswordCompromisedError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {"password": "password appears in a compromised-password list"},
            },
        )
    if isinstance(exc, MfaLockedError):
        return HTTPException(
            status_code=429,
            detail={"code": "rate_limited"},
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, InvalidMfaCodeError):
        return HTTPException(status_code=401, detail={"code": "invalid_mfa_code"})
    if isinstance(exc, MfaAlreadyEnabledError):
        return HTTPException(status_code=409, detail={"code": "conflict"})
    if isinstance(exc, InvalidPasswordResetError):
        return HTTPException(status_code=401, detail={"code": "token_invalid"})
    if isinstance(exc, AuthBusyError):
        return HTTPException(status_code=503, detail={"code": "service_unavailable"})
    if isinstance(exc, InvalidMfaChallengeError):
        return HTTPException(status_code=401, detail={"code": "token_invalid"})
    if isinstance(exc, TokenExpiredError):
        return HTTPException(status_code=401, detail={"code": "token_expired"})
    if isinstance(exc, EmailTakenError):
        return HTTPException(status_code=409, detail={"code": "email_taken"})
    if isinstance(exc, InvalidCredentialsError):
        return HTTPException(status_code=401, detail={"code": "invalid_credentials"})
    if isinstance(exc, SessionRevokedError):
        return HTTPException(status_code=401, detail={"code": "session_revoked"})
    if isinstance(exc, TenantMismatchError):
        return HTTPException(status_code=403, detail={"code": "tenant_mismatch"})
    if isinstance(exc, InactiveUserError):
        return HTTPException(status_code=403, detail={"code": "forbidden_role"})
    if isinstance(exc, InvalidTokenError):
        return HTTPException(status_code=401, detail={"code": "token_invalid"})
    return HTTPException(status_code=500, detail={"code": "internal_error"})


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    try:
        tokens = await service.register(
            email=payload.email,
            password=payload.password,
            name=payload.name,
            phone=payload.phone,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        )
    except Exception as exc:
        raise _error(exc) from exc
    _set_refresh_cookie(response, request, tokens)
    return _login_response(tokens)


@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(verify_csrf), Depends(enforce_login_rate_limit)],
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    try:
        result = await service.login(
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        )
    except Exception as exc:
        raise _error(exc) from exc
    return _login_payload(result, response, request)


@router.post(
    "/mfa/setup",
    response_model=MfaSetupResponse,
    dependencies=[Depends(verify_csrf)],
)
async def setup_mfa(
    payload: MfaTokenRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MfaSetupResponse:
    try:
        result = await service.setup_mfa(mfa_token=payload.mfa_token)
    except Exception as exc:
        raise _error(exc) from exc
    return MfaSetupResponse(secret=result.secret, otpauth_uri=result.otpauth_uri)


@router.post(
    "/mfa/confirm",
    response_model=MfaConfirmResponse,
    dependencies=[Depends(verify_csrf)],
)
async def confirm_mfa(
    payload: MfaCodeRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MfaConfirmResponse:
    try:
        result = await service.confirm_mfa(
            mfa_token=payload.mfa_token,
            code=payload.code,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        )
    except Exception as exc:
        raise _error(exc) from exc
    _set_refresh_cookie(response, request, result.tokens)
    tokens = _login_response(result.tokens)
    return MfaConfirmResponse(
        **tokens.model_dump(),
        recovery_codes=list(result.recovery_codes),
    )


@router.post(
    "/mfa/verify",
    response_model=LoginResponse,
    dependencies=[Depends(verify_csrf)],
)
async def verify_mfa(
    payload: MfaCodeRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    try:
        tokens = await service.verify_mfa(
            mfa_token=payload.mfa_token,
            code=payload.code,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        )
    except Exception as exc:
        raise _error(exc) from exc
    _set_refresh_cookie(response, request, tokens)
    return _login_response(tokens)


@router.post(
    "/password/forgot",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_csrf)],
)
async def forgot_password(
    payload: PasswordForgotRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    try:
        await service.request_password_reset(email=payload.email)
    except Exception as exc:
        raise _error(exc) from exc
    return MessageResponse(
        message="If the account exists, password reset instructions will be sent."
    )


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_csrf)],
)
async def reset_password(
    payload: PasswordResetRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    try:
        await service.reset_password(token=payload.token, password=payload.password)
    except Exception as exc:
        raise _error(exc) from exc
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post(
    "/refresh",
    response_model=LoginResponse,
    dependencies=[Depends(verify_csrf)],
)
async def refresh(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    settings = request.app.state.settings
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=401, detail={"code": "token_invalid"})
    try:
        tokens = await service.refresh(
            refresh_token=raw_token,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        )
    except Exception as exc:
        error = _error(exc)
        if error.status_code < 500:
            temp = Response()
            _clear_refresh_cookie(temp, request)
            error.headers = {"set-cookie": temp.headers["set-cookie"]}
        raise error from exc
    _set_refresh_cookie(response, request, tokens)
    return _login_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_csrf)])
async def logout(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    settings = request.app.state.settings
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token:
        await service.logout(refresh_token=raw_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.headers["Cache-Control"] = "no-store"
    _clear_refresh_cookie(response, request)
    return response


@router.get("/session", response_model=SessionDTO)
async def session(
    request: Request,
    user: Annotated[UserAccount, Depends(get_current_user)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> SessionDTO:
    offer_accepted = await OfferRepository(db_session).has_accepted_current(user_id=user.id)
    return SessionDTO(
        user=UserDTO.from_domain(user),
        tenant_id=cast(UUID, request.state.tenant_id),
        role=user.role,
        permissions=list(user.permissions),
        offer_accepted=offer_accepted,
        mfa_enabled=await service.mfa_enabled(user.id),
    )


__all__ = ["router"]
