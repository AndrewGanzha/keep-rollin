from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import (
    get_auth_service,
    get_current_user,
    get_password_hasher,
    require_permission,
    verify_csrf,
)
from app.api.deps import get_db_session
from src.application.dtos.admin_user_dto import (
    AdminUserCreateRequest,
    AdminUserDTO,
    AdminUserListDTO,
)
from src.application.services.admin_users import (
    AdminUserNotFoundError,
    AdminUserService,
    ForbiddenAdminActionError,
    LastOwnerError,
    SelfDeactivationError,
)
from src.application.services.audit import AuditWriter
from src.application.services.auth import (
    AuthService,
    InvalidMfaCodeError,
    MfaLockedError,
)
from src.domain.entities.user_account import (
    AuthBusyError,
    EmailTakenError,
    InactiveUserError,
    InvalidTokenError,
    UserAccount,
)
from src.domain.policies.password_policy import PasswordCompromisedError
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.infrastructure.postgres.repositories.admin_user_repository import (
    AdminUserRepository,
)
from src.infrastructure.postgres.repositories.audit_repository import AuditRepository
from src.infrastructure.postgres.repositories.auth_repository import AuthRepository


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/admin/users",
    tags=["admin-users"],
    dependencies=[
        Depends(require_permission("admins.manage")),
        Depends(no_store),
    ],
)


def get_admin_user_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AdminUserService:
    settings = request.app.state.settings
    tenant_id = cast(UUID | None, getattr(request.state, "tenant_id", None))
    if tenant_id is None:
        raise HTTPException(status_code=404, detail={"code": "tenant_not_found"})
    return AdminUserService(
        AdminUserRepository(session),
        AuthRepository(session),
        auth_service,
        get_password_hasher(),
        AuditWriter(AuditRepository(session), tenant_id=tenant_id),
        password_work_timeout_seconds=settings.password_work_timeout_seconds,
    )


def _admin_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MfaLockedError):
        return HTTPException(
            status_code=429,
            detail={"code": "rate_limited"},
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, InvalidTokenError):
        return HTTPException(
            status_code=401,
            detail={"code": "token_invalid"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if isinstance(exc, InvalidMfaCodeError):
        return HTTPException(status_code=401, detail={"code": "invalid_mfa_code"})
    if isinstance(exc, EmailTakenError):
        return HTTPException(status_code=409, detail={"code": "email_taken"})
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
    if isinstance(exc, AdminUserNotFoundError):
        return HTTPException(status_code=404, detail={"code": "not_found"})
    if isinstance(exc, SelfDeactivationError):
        return HTTPException(
            status_code=409,
            detail={"code": "self_deactivation_not_allowed"},
        )
    if isinstance(exc, LastOwnerError):
        return HTTPException(status_code=409, detail={"code": "last_owner"})
    if isinstance(exc, (ForbiddenAdminActionError, InactiveUserError)):
        return HTTPException(status_code=403, detail={"code": "forbidden_role"})
    return HTTPException(status_code=500, detail={"code": "internal_error"})


@router.get("", response_model=AdminUserListDTO)
async def list_users(
    service: Annotated[AdminUserService, Depends(get_admin_user_service)],
    role: Annotated[Literal["owner", "admin", "user"] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=MAX_DATABASE_INTEGER)] = 0,
) -> AdminUserListDTO:
    page = await service.list_users(role=role, query=q, limit=limit, offset=offset)
    return AdminUserListDTO(
        items=[AdminUserDTO.from_info(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "",
    response_model=AdminUserDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
async def create_admin(
    payload: AdminUserCreateRequest,
    request: Request,
    actor: Annotated[UserAccount, Depends(get_current_user)],
    service: Annotated[AdminUserService, Depends(get_admin_user_service)],
) -> AdminUserDTO:
    try:
        created = await service.create(
            actor=actor,
            email=payload.email,
            name=payload.name,
            password=payload.password,
            mfa_code=payload.mfa_code,
            ip=request.client.host if request.client else None,
            request_id=str(getattr(request.state, "request_id", "")) or None,
        )
    except Exception as exc:
        raise _admin_error(exc) from exc
    return AdminUserDTO.from_info(created)


@router.post(
    "/{user_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_csrf)],
)
async def deactivate_user(
    user_id: UUID,
    request: Request,
    actor: Annotated[UserAccount, Depends(get_current_user)],
    service: Annotated[AdminUserService, Depends(get_admin_user_service)],
) -> Response:
    try:
        await service.deactivate(
            actor=actor,
            target_id=user_id,
            ip=request.client.host if request.client else None,
            request_id=str(getattr(request.state, "request_id", "")) or None,
        )
    except Exception as exc:
        raise _admin_error(exc) from exc
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.headers["Cache-Control"] = "no-store"
    return response


__all__ = ["router"]
