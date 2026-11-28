from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit_deps import StaffAudit
from app.api.auth_deps import get_current_user, require_permission, verify_csrf
from app.api.deps import get_db_session
from app.api.idempotency import REPLAY_RESPONSE_HEADERS, Idempotency, IdempotencyKey
from src.application.dtos.admin_lot_dto import (
    BulkLotRequest,
    BulkLotResponse,
    CreateLotRequest,
    LotStatusRequest,
    UpdateLotRequest,
)
from src.application.dtos.lot_dto import LotDTO, LotPageDTO
from src.domain.entities.lot import LotStatus
from src.domain.entities.user_account import UserAccount
from src.domain.exceptions import (
    LotHasActiveRentalError,
    LotUnavailableError,
    OccupancyConflictError,
)
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.infrastructure.postgres.repositories.admin_lot_repository import (
    AdminLotNotFoundError,
    AdminLotRepository,
    AdminLotSlugTakenError,
    AdminLotVersionConflictError,
    InvalidLotFieldsError,
)
from src.infrastructure.postgres.repositories.file_repository import UnknownLotPhotoError


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/admin/lots",
    tags=["admin-lots"],
    dependencies=[Depends(require_permission("catalog.manage")), Depends(no_store)],
)


def get_admin_lot_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminLotRepository:
    return AdminLotRepository(session)


Repository = Annotated[AdminLotRepository, Depends(get_admin_lot_repository)]
_LOT_ERRORS = (
    AdminLotNotFoundError,
    UnknownLotPhotoError,
    AdminLotSlugTakenError,
    AdminLotVersionConflictError,
    InvalidLotFieldsError,
)


def _lot_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (AdminLotNotFoundError, UnknownLotPhotoError)):
        return HTTPException(status_code=404, detail={"code": "not_found"})
    if isinstance(exc, AdminLotSlugTakenError):
        return HTTPException(status_code=409, detail={"code": "slug_taken"})
    if isinstance(exc, AdminLotVersionConflictError):
        return HTTPException(status_code=409, detail={"code": "stale_version"})
    if isinstance(exc, InvalidLotFieldsError):
        return HTTPException(
            status_code=422,
            detail={"code": "validation_error", "fields": exc.fields},
        )
    raise exc


@router.get("", response_model=LotPageDTO)
async def list_lots(
    repository: Repository,
    category_id: UUID | None = None,
    status: LotStatus | None = None,
    q: Annotated[str | None, Query(max_length=120, pattern=r"^[^\x00]*$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=MAX_DATABASE_INTEGER)] = 0,
) -> LotPageDTO:
    items, total = await repository.list_page(
        category_id=category_id,
        status=status,
        query=q.strip() if q is not None else None,
        limit=limit,
        offset=offset,
    )
    return LotPageDTO(
        items=[LotDTO.from_domain(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{id}", response_model=LotDTO)
async def get_lot(lot_id: Annotated[UUID, Path(alias="id")], repository: Repository) -> LotDTO:
    try:
        return LotDTO.from_domain(await repository.get(lot_id))
    except AdminLotNotFoundError as exc:
        raise _lot_error(exc) from exc


@router.post(
    "",
    response_model=LotDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
async def create_lot(payload: CreateLotRequest, repository: Repository) -> LotDTO:
    try:
        return LotDTO.from_domain(await repository.create(payload))
    except _LOT_ERRORS as exc:
        raise _lot_error(exc) from exc


@router.post(
    "/bulk",
    response_model=BulkLotResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
    responses={
        201: {"headers": REPLAY_RESPONSE_HEADERS},
        401: {"description": "Authentication required"},
        403: {"description": "Owner permission or CSRF verification required"},
        404: {"description": "Category or photo not found"},
        409: {"description": "slug_taken"},
    },
)
async def create_bulk_lots(
    payload: BulkLotRequest,
    response: Response,
    repository: Repository,
    actor: Annotated[UserAccount, Depends(get_current_user)],
    key: IdempotencyKey,
    idempotency: Idempotency,
) -> BulkLotResponse:
    cached = await idempotency.replay(actor.id, key, "admin.lots.bulk", payload, response)
    if cached is not None:
        return BulkLotResponse.model_validate(cached)

    try:
        lots = await repository.create_bulk(payload.template, payload.count)
    except _LOT_ERRORS as exc:
        raise _lot_error(exc) from exc
    result = BulkLotResponse(items=[LotDTO.from_domain(lot) for lot in lots])
    await idempotency.save(actor.id, key, result)
    return result


@router.patch(
    "/{id}",
    response_model=LotDTO,
    dependencies=[Depends(verify_csrf)],
)
async def update_lot(
    lot_id: Annotated[UUID, Path(alias="id")], payload: UpdateLotRequest, repository: Repository
) -> LotDTO:
    try:
        return LotDTO.from_domain(await repository.update(lot_id, payload))
    except _LOT_ERRORS as exc:
        raise _lot_error(exc) from exc


@router.post(
    "/{id}/status",
    response_model=LotDTO,
    dependencies=[Depends(verify_csrf)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Owner permission or CSRF verification required"},
        404: {"description": "Lot not found"},
        409: {"description": "lot_has_active_rental, lot_unavailable or slot_taken"},
    },
)
async def set_lot_status(
    lot_id: Annotated[UUID, Path(alias="id")],
    payload: LotStatusRequest,
    repository: Repository,
    actor: Annotated[UserAccount, Depends(get_current_user)],
    audit: Annotated[StaffAudit, Depends()],
) -> LotDTO:
    try:
        lot, old_status = await repository.set_status(lot_id, payload.status, actor_id=actor.id)
    except AdminLotNotFoundError as exc:
        raise _lot_error(exc) from exc
    except LotHasActiveRentalError as exc:
        raise HTTPException(status_code=409, detail={"code": "lot_has_active_rental"}) from exc
    except LotUnavailableError as exc:
        raise HTTPException(status_code=409, detail={"code": "lot_unavailable"}) from exc
    except OccupancyConflictError as exc:
        raise HTTPException(status_code=409, detail={"code": "slot_taken"}) from exc
    if old_status is not None:
        await audit.record(
            action="lot.status_changed",
            entity_type="lot",
            entity_id=lot.id,
            metadata={"old_status": old_status, "new_status": lot.status},
        )
    return LotDTO.from_domain(lot)
