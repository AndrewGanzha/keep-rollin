from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit_deps import StaffAudit
from app.api.auth_deps import get_current_user, verify_csrf
from app.api.deps import get_db_session
from src.application.dtos.battery_stock_dto import (
    BatteryStock,
    BatteryType,
    CreateBatteryStockRequest,
    UpdateBatteryStockRequest,
)
from src.domain.entities.user_account import UserAccount
from src.infrastructure.postgres.models.battery_stock_record import BatteryStockRecord
from src.infrastructure.postgres.repositories.battery_stock_repository import (
    BatteryStockBelowCommittedError,
    BatteryStockConflictError,
    BatteryStockInUseError,
    BatteryStockNotFoundError,
    BatteryStockRepository,
)


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def require_owner(user: Annotated[UserAccount, Depends(get_current_user)]) -> None:
    if user.role != "owner":
        raise HTTPException(status_code=403, detail={"code": "forbidden_role"})


router = APIRouter(
    prefix="/api/v1/admin/batteries",
    tags=["admin-batteries"],
    dependencies=[Depends(require_owner), Depends(no_store)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Owner access required. Writes require CSRF verification."},
    },
)


def get_battery_stock_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BatteryStockRepository:
    return BatteryStockRepository(session)


Repository = Annotated[BatteryStockRepository, Depends(get_battery_stock_repository)]
Audit = Annotated[StaffAudit, Depends()]


def _stock_item(stock: BatteryStockRecord, peak: int) -> BatteryStock:
    return BatteryStock(
        battery_type=stock.battery_type,
        name=stock.name,
        quantity=stock.quantity,
        peak_committed=peak,
    )


@router.get("", operation_id="listBatteryStock", response_model=list[BatteryStock])
async def list_battery_stock(repository: Repository) -> list[BatteryStock]:
    return [
        _stock_item(stock, peak) for stock, peak in await repository.list(now=datetime.now(UTC))
    ]


@router.post(
    "",
    response_model=BatteryStock,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
    responses={409: {"description": "Stock already exists for this battery type"}},
)
async def create_battery_stock(
    payload: CreateBatteryStockRequest,
    repository: Repository,
    audit: Audit,
) -> BatteryStock:
    try:
        stock, peak = await repository.create(payload.battery_type, payload.name, payload.quantity)
    except BatteryStockConflictError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "conflict", "detail": str(exc)}
        ) from exc
    await audit.record(
        action="battery_stock.created", entity_type="battery_stock", entity_id=stock.id
    )
    return _stock_item(stock, peak)


@router.patch(
    "/{battery_type:path}",
    operation_id="updateBatteryStock",
    response_model=BatteryStock,
    dependencies=[Depends(verify_csrf)],
    responses={
        404: {"description": "Battery type not found"},
        409: {"description": "stock_below_committed"},
    },
)
async def update_battery_stock(
    battery_type: BatteryType,
    payload: UpdateBatteryStockRequest,
    repository: Repository,
    audit: Audit,
) -> BatteryStock:
    try:
        stock, peak = await repository.update_quantity(
            battery_type, payload.quantity, now=datetime.now(UTC)
        )
    except BatteryStockNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found"}) from exc
    except BatteryStockBelowCommittedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stock_below_committed",
                "detail": (
                    f"Нельзя установить остаток {payload.quantity} шт.: "
                    f"уже забронировано {exc.peak_committed} шт."
                ),
                "fields": {
                    "quantity": f"Занято {exc.peak_committed} шт. — уменьшить нельзя",
                    "requested_quantity": str(payload.quantity),
                    "peak_committed": str(exc.peak_committed),
                },
            },
        ) from exc
    await audit.record(
        action="battery_stock.updated", entity_type="battery_stock", entity_id=stock.id
    )
    return _stock_item(stock, peak)


@router.delete(
    "/{battery_type:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_csrf)],
    responses={
        404: {"description": "Battery type not found"},
        409: {"description": "Battery type is referenced by rental history"},
    },
)
async def delete_battery_stock(
    battery_type: BatteryType, repository: Repository, audit: Audit
) -> None:
    try:
        stock = await repository.delete(battery_type)
    except BatteryStockNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found"}) from exc
    except BatteryStockInUseError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "conflict", "detail": str(exc)}
        ) from exc
    await audit.record(
        action="battery_stock.deleted", entity_type="battery_stock", entity_id=stock.id
    )
