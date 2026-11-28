from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit_deps import StaffAudit
from app.api.auth_deps import require_permission, verify_csrf
from app.api.deps import get_db_session
from src.application.dtos.admin_category_dto import (
    AdminCategoryDTO,
    AdminCategoryPageDTO,
    CreateCategoryRequest,
    UpdateCategoryRequest,
    UpdateCharacteristicsRequest,
)
from src.application.handlers.admin_category.commands.create import (
    CreateCategoryCommand,
    CreateCategoryHandler,
)
from src.application.handlers.admin_category.commands.update import (
    UpdateCategoryCommand,
    UpdateCategoryHandler,
)
from src.application.handlers.admin_category.commands.update_characteristics import (
    UpdateCategoryCharacteristicsCommand,
    UpdateCategoryCharacteristicsHandler,
)
from src.application.handlers.admin_category.queries.list import (
    ListAdminCategoriesHandler,
    ListAdminCategoriesQuery,
)
from src.application.repositories.i_admin_category_repository import CharacteristicUpsert
from src.domain.entities.category import (
    CategoryNotFoundError,
    CategorySlugTakenError,
    CategoryVersionConflictError,
)
from src.domain.entities.characteristic import CharacteristicInUseError
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.infrastructure.postgres.repositories.admin_category_repository import (
    AdminCategoryRepository,
)


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/admin/categories",
    tags=["admin-categories"],
    dependencies=[
        Depends(require_permission("catalog.manage")),
        Depends(no_store),
    ],
)


def get_admin_category_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminCategoryRepository:
    return AdminCategoryRepository(session)


def get_list_handler(
    repository: Annotated[AdminCategoryRepository, Depends(get_admin_category_repository)],
) -> ListAdminCategoriesHandler:
    return ListAdminCategoriesHandler(repository)


def get_create_handler(
    repository: Annotated[AdminCategoryRepository, Depends(get_admin_category_repository)],
) -> CreateCategoryHandler:
    return CreateCategoryHandler(repository)


def get_update_handler(
    repository: Annotated[AdminCategoryRepository, Depends(get_admin_category_repository)],
) -> UpdateCategoryHandler:
    return UpdateCategoryHandler(repository)


def get_update_characteristics_handler(
    repository: Annotated[AdminCategoryRepository, Depends(get_admin_category_repository)],
) -> UpdateCategoryCharacteristicsHandler:
    return UpdateCategoryCharacteristicsHandler(repository)


def _category_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CategoryNotFoundError):
        return HTTPException(status_code=404, detail={"code": "not_found"})
    if isinstance(exc, CategorySlugTakenError):
        return HTTPException(status_code=409, detail={"code": "slug_taken"})
    if isinstance(exc, CategoryVersionConflictError):
        return HTTPException(status_code=409, detail={"code": "stale_version"})
    if isinstance(exc, CharacteristicInUseError):
        return HTTPException(status_code=409, detail={"code": "characteristic_in_use"})
    raise exc


@router.get("", response_model=AdminCategoryPageDTO)
async def list_categories(
    handler: Annotated[ListAdminCategoriesHandler, Depends(get_list_handler)],
    include_archived: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=MAX_DATABASE_INTEGER)] = 0,
) -> AdminCategoryPageDTO:
    return await handler.handle(
        ListAdminCategoriesQuery(
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
    )


@router.post(
    "",
    response_model=AdminCategoryDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
async def create_category(
    payload: CreateCategoryRequest,
    handler: Annotated[CreateCategoryHandler, Depends(get_create_handler)],
    audit: Annotated[StaffAudit, Depends()],
) -> AdminCategoryDTO:
    try:
        category = await handler.handle(
            CreateCategoryCommand(
                name=payload.name,
                slug=payload.slug,
                description=payload.description,
            )
        )
    except (CategoryNotFoundError, CategorySlugTakenError, CategoryVersionConflictError) as exc:
        raise _category_error(exc) from exc
    await audit.record(
        action="category.created",
        entity_type="category",
        entity_id=category.id,
        metadata={"is_archived": category.is_archived},
    )
    return category


@router.patch(
    "/{category_id}",
    response_model=AdminCategoryDTO,
    dependencies=[Depends(verify_csrf)],
)
async def update_category(
    category_id: UUID,
    payload: UpdateCategoryRequest,
    handler: Annotated[UpdateCategoryHandler, Depends(get_update_handler)],
    audit: Annotated[StaffAudit, Depends()],
) -> AdminCategoryDTO:
    changes = payload.model_dump(exclude_unset=True)
    changes.pop("version")
    try:
        category = await handler.handle(
            UpdateCategoryCommand(
                category_id=category_id,
                version=payload.version,
                changes=changes,
            )
        )
    except (CategoryNotFoundError, CategorySlugTakenError, CategoryVersionConflictError) as exc:
        raise _category_error(exc) from exc
    await audit.record(
        action="category.updated",
        entity_type="category",
        entity_id=category.id,
        metadata={"changed_fields": sorted(changes), "is_archived": category.is_archived},
    )
    return category


@router.put(
    "/{category_id}/characteristics",
    response_model=AdminCategoryDTO,
    dependencies=[Depends(verify_csrf)],
)
async def update_characteristics(
    category_id: UUID,
    payload: UpdateCharacteristicsRequest,
    handler: Annotated[
        UpdateCategoryCharacteristicsHandler,
        Depends(get_update_characteristics_handler),
    ],
    audit: Annotated[StaffAudit, Depends()],
) -> AdminCategoryDTO:
    definitions = [
        CharacteristicUpsert(
            code=item.code,
            name=item.name,
            type=item.type,
            unit=item.unit,
            is_required=item.is_required,
            options=tuple(item.options),
            sort=item.sort,
            is_archived=item.is_archived,
        )
        for item in payload.items
    ]
    try:
        category = await handler.handle(
            UpdateCategoryCharacteristicsCommand(
                category_id=category_id,
                version=payload.version,
                definitions=definitions,
            )
        )
    except (
        CategoryNotFoundError,
        CategoryVersionConflictError,
        CharacteristicInUseError,
    ) as exc:
        raise _category_error(exc) from exc
    await audit.record(
        action="category.characteristics_updated",
        entity_type="category",
        entity_id=category.id,
        metadata={"count": len(definitions)},
    )
    return category


__all__ = ["router"]
