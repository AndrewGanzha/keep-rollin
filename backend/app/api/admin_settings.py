from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import require_permission, verify_csrf
from app.api.deps import get_db_session
from src.application.dtos.admin_settings_dto import AdminSettingsDTO, UpdateSettingsRequest
from src.application.handlers.admin_settings.settings import (
    GetAdminSettingsHandler,
    GetAdminSettingsQuery,
    UpdateSettingsCommand,
    UpdateSettingsHandler,
)
from src.application.repositories.i_admin_settings_repository import IAdminSettingsRepository
from src.domain.entities.tenant_profile import (
    InvalidTenantProfileError,
    SettingsNotFoundError,
    SettingsVersionConflictError,
)
from src.infrastructure.postgres.repositories.admin_settings_repository import (
    AdminSettingsRepository,
)


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/admin/settings",
    tags=["admin-settings"],
    dependencies=[
        Depends(require_permission("settings.manage")),
        Depends(no_store),
    ],
)


def get_admin_settings_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> IAdminSettingsRepository:
    return AdminSettingsRepository(session)


def get_get_handler(
    repository: Annotated[IAdminSettingsRepository, Depends(get_admin_settings_repository)],
) -> GetAdminSettingsHandler:
    return GetAdminSettingsHandler(repository)


def get_update_handler(
    repository: Annotated[IAdminSettingsRepository, Depends(get_admin_settings_repository)],
) -> UpdateSettingsHandler:
    return UpdateSettingsHandler(repository)


def _settings_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SettingsNotFoundError):
        return HTTPException(status_code=404, detail={"code": "not_found"})
    if isinstance(exc, SettingsVersionConflictError):
        return HTTPException(status_code=409, detail={"code": "stale_version"})
    if isinstance(exc, InvalidTenantProfileError):
        return HTTPException(
            status_code=422,
            detail={"code": "validation_error", "fields": {"policies": str(exc)}},
        )
    raise exc


@router.get("", response_model=AdminSettingsDTO)
async def get_settings(
    handler: Annotated[GetAdminSettingsHandler, Depends(get_get_handler)],
) -> AdminSettingsDTO:
    try:
        return await handler.handle(GetAdminSettingsQuery())
    except (SettingsNotFoundError, InvalidTenantProfileError) as exc:
        raise _settings_error(exc) from exc


@router.patch(
    "",
    response_model=AdminSettingsDTO,
    dependencies=[Depends(verify_csrf)],
)
async def update_settings(
    payload: UpdateSettingsRequest,
    handler: Annotated[UpdateSettingsHandler, Depends(get_update_handler)],
) -> AdminSettingsDTO:
    changes = payload.model_dump(exclude_unset=True, exclude={"version", "policies"})
    try:
        return await handler.handle(
            UpdateSettingsCommand(
                version=payload.version,
                changes=changes,
                policies_patch=payload.policies,
            )
        )
    except (
        SettingsNotFoundError,
        SettingsVersionConflictError,
        InvalidTenantProfileError,
    ) as exc:
        raise _settings_error(exc) from exc


__all__ = ["router"]
