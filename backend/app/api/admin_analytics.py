import csv
import re
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from datetime import timedelta
from io import StringIO
from typing import Annotated, Literal, cast
from unicodedata import normalize
from uuid import UUID
from zoneinfo import ZoneInfo

from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BeforeValidator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import Send

from app.api.auth_deps import require_permission
from app.api.deps import get_db_session
from app.api.public_period import parse_public_period
from app.db import configure_session
from app.models import Tenant
from src.application.dtos.analytics_dto import (
    AnalyticsComparison,
    AnalyticsExportRow,
    AnalyticsGroupBy,
    AnalyticsLotDetail,
    AnalyticsMetrics,
    AnalyticsRevenue,
    AnalyticsSummary,
)
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.repositories.analytics_repository import AnalyticsRepository

MAX_PERIOD_DAYS = 366
CSV_BATCH_SIZE = 256
CSV_HEADERS = (
    "ID аренды",
    "Лот",
    "Категория",
    "Начало",
    "Окончание",
    "Статус",
    "Сумма в минорных единицах",
    "Валюта",
)


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/admin/analytics",
    tags=["admin-analytics"],
    dependencies=[Depends(require_permission("analytics.view")), Depends(no_store)],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Analytics permission required"},
    },
)


def _require_date_time(value: object) -> object:
    if isinstance(value, str) and not re.match(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}", value):
        raise ValueError("must be a date and time with a UTC offset")
    return value


ReportBound = Annotated[AwareDatetime, BeforeValidator(_require_date_time)]


def get_period(
    from_: Annotated[ReportBound, Query(alias="from")],
    to: ReportBound,
) -> TimeRange:
    return parse_public_period(from_, to, max_days=MAX_PERIOD_DAYS, normalize_to_utc=True)


def get_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AnalyticsRepository:
    return AnalyticsRepository(session)


Period = Annotated[TimeRange, Depends(get_period)]
Repository = Annotated[AnalyticsRepository, Depends(get_repository)]


@router.get("/summary", operation_id="getAnalyticsSummary")
async def analytics_summary(
    period: Period, repository: Repository, category_id: UUID | None = None
) -> AnalyticsSummary:
    return await repository.summary(period, category_id=category_id)


@router.get("/revenue", operation_id="getAnalyticsRevenue")
async def analytics_revenue(
    period: Period,
    repository: Repository,
    group_by: AnalyticsGroupBy,
    category_id: UUID | None = None,
) -> AnalyticsRevenue:
    return AnalyticsRevenue(
        group_by=group_by,
        buckets=await repository.buckets(period, group_by, category_id=category_id),
    )


@router.get(
    "/lots/{lot_id}",
    operation_id="getAnalyticsLot",
    responses={404: {"description": "Lot not found"}},
)
async def analytics_lot(
    lot_id: UUID,
    period: Period,
    repository: Repository,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=MAX_DATABASE_INTEGER)] = 0,
) -> AnalyticsLotDetail:
    lot = await repository.lot(lot_id)
    if lot is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    summary = await repository.summary(period, lot_id=lot_id)
    return AnalyticsLotDetail(
        lot=lot,
        period_from=period.start,
        period_to=period.end,
        summary=summary,
        daily=await repository.buckets(period, "day", lot_id=lot_id),
        rentals=await repository.rentals(period, lot_id, limit=limit, offset=offset),
        rentals_total=summary.rentals_count,
    )


@router.get("/utilization", operation_id="getAnalyticsUtilization")
async def analytics_utilization(
    period: Period,
    repository: Repository,
    group_by: AnalyticsGroupBy = "lot",
    category_id: UUID | None = None,
) -> AnalyticsRevenue:
    return AnalyticsRevenue(
        group_by=group_by,
        buckets=await repository.buckets(period, group_by, category_id=category_id),
    )


@router.get("/compare", operation_id="compareAnalytics")
async def analytics_compare(
    period: Period,
    repository: Repository,
    compare_from: ReportBound,
    compare_to: ReportBound,
    category_id: UUID | None = None,
) -> AnalyticsComparison:
    previous_period = parse_public_period(
        compare_from,
        compare_to,
        max_days=MAX_PERIOD_DAYS,
        from_field="compare_from",
        to_field="compare_to",
        normalize_to_utc=True,
    )
    current = await repository.summary(period, category_id=category_id)
    previous = (
        current
        if previous_period == period
        else await repository.summary(previous_period, category_id=category_id)
    )
    return AnalyticsComparison(
        current=current,
        previous=previous,
        delta=AnalyticsMetrics(
            revenue_minor=current.revenue_minor - previous.revenue_minor,
            rentals_count=current.rentals_count - previous.rentals_count,
            cancelled_count=current.cancelled_count - previous.cancelled_count,
            overdue_count=current.overdue_count - previous.overdue_count,
            avg_rental_minor=current.avg_rental_minor - previous.avg_rental_minor,
            utilization_pct=round(current.utilization_pct - previous.utilization_pct, 1),
        ),
    )


def spreadsheet_text(value: str) -> str:
    leading = normalize("NFKC", value).lstrip().lstrip("\ufeff\u200b\u200c\u200d").lstrip()
    if value.startswith(("\t", "\r", "\n")) or leading.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


async def rental_report(rows: AsyncIterator[AnalyticsExportRow]) -> AsyncGenerator[str]:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_HEADERS)
    yield "\ufeff" + buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)

    buffered_rows = 0
    async for row in rows:
        writer.writerow(
            (
                str(row.id),
                spreadsheet_text(row.lot_name),
                spreadsheet_text(row.category_name),
                row.start_time.isoformat(),
                row.end_time.isoformat(),
                row.status,
                row.price_minor,
                spreadsheet_text(row.currency),
            )
        )
        buffered_rows += 1
        if buffered_rows == CSV_BATCH_SIZE:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            buffered_rows = 0
    if buffer.tell():
        yield buffer.getvalue()


async def export_body(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    database_role: str,
    period: TimeRange,
) -> AsyncGenerator[str]:
    session = factory()
    configure_session(session, tenant_id=tenant_id, database_role=database_role)
    try:
        rows = AnalyticsRepository(session).iter_export(period)
        async with aclosing(rows), aclosing(rental_report(rows)) as report:
            async for chunk in report:
                yield chunk
    finally:
        with CancelScope(shield=True):
            await session.close()


class AnalyticsCSVResponse(StreamingResponse):
    def __init__(self, body: AsyncGenerator[str], *, filename: str) -> None:
        self.export = body
        super().__init__(
            body,
            media_type="text/csv",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Accel-Buffering": "no",
            },
        )

    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            with CancelScope(shield=True):
                await self.export.aclose()


@router.get(
    "/export",
    operation_id="exportAnalytics",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Rental CSV report",
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {"Content-Disposition": {"schema": {"type": "string"}}},
        }
    },
)
async def analytics_export(
    request: Request,
    period: Period,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    report: Literal["rentals"],
    format: Literal["csv"] = "csv",
) -> StreamingResponse:
    factory = cast(async_sessionmaker[AsyncSession] | None, request.app.state.session_factory)
    if factory is None:
        raise HTTPException(status_code=503, detail={"code": "service_unavailable"})
    tenant_id = cast(UUID, request.state.tenant_id)
    database_role = request.app.state.settings.database_role
    tenant = (
        await session.execute(select(Tenant.slug, Tenant.timezone).where(Tenant.id == tenant_id))
    ).one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "tenant_not_found"})
    slug, timezone_name = tenant
    filename_slug = re.sub(r"[^a-zA-Z0-9_-]", "-", slug).strip("-") or "analytics"
    timezone = ZoneInfo(timezone_name)
    try:
        first_day = period.start.astimezone(timezone).date()
        last_day = (period.end - timedelta(microseconds=1)).astimezone(timezone).date()
    except OverflowError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_error", "fields": {"from": "tenant date is out of range"}},
        ) from exc
    filename = f"{filename_slug}_{report}_{first_day}_{last_day}.{format}"
    request.state.stream_with_own_session = True
    return AnalyticsCSVResponse(
        export_body(factory, tenant_id, database_role, period), filename=filename
    )
