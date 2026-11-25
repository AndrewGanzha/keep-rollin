from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.auth_deps import get_auth_service, get_current_user, verify_csrf
from src.application.dtos.auth_dto import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    SessionDTO,
    UserDTO,
)
from src.application.services.auth import AuthService, IssuedTokens
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


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, PasswordCompromisedError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {"password": "password appears in a compromised-password list"},
            },
        )
    if isinstance(exc, AuthBusyError):
        return HTTPException(status_code=503, detail={"code": "service_unavailable"})
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
    dependencies=[Depends(verify_csrf)],
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    try:
        tokens = await service.login(
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        )
    except Exception as exc:
        raise _error(exc) from exc
    _set_refresh_cookie(response, request, tokens)
    return _login_response(tokens)


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
    _clear_refresh_cookie(response, request)
    return response


@router.get("/session", response_model=SessionDTO)
async def session(
    request: Request,
    user: Annotated[UserAccount, Depends(get_current_user)],
) -> SessionDTO:
    return SessionDTO(
        user=UserDTO.from_domain(user),
        tenant_id=cast(UUID, request.state.tenant_id),
        role=user.role,
        permissions=list(user.permissions),
        offer_accepted=False,
    )


__all__ = ["router"]
