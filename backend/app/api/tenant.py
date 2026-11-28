from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from src.application.dtos.tenant_dto import TenantDTO
from src.application.handlers.tenant.queries.get import (
    GetPublicTenantHandler,
    GetPublicTenantQuery,
)
from src.infrastructure.postgres.repositories.tenant_profile_repository import (
    TenantProfileRepository,
)

router = APIRouter(prefix="/api/v1/public", tags=["public-tenant"])


def get_tenant_profile_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TenantProfileRepository:
    return TenantProfileRepository(session)


def get_public_tenant_handler(
    repository: Annotated[TenantProfileRepository, Depends(get_tenant_profile_repository)],
) -> GetPublicTenantHandler:
    return GetPublicTenantHandler(repository)


@router.get("/tenant", response_model=TenantDTO)
async def get_public_tenant(
    handler: Annotated[GetPublicTenantHandler, Depends(get_public_tenant_handler)],
    response: Response,
) -> TenantDTO:
    tenant = await handler.handle(GetPublicTenantQuery())
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    response.headers["Cache-Control"] = "max-age=300"
    return tenant
