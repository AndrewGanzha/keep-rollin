from collections.abc import AsyncGenerator
from uuid import UUID

from anyio import CancelScope
from sqlalchemy import RowMapping, TextClause, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.dtos.analytics_dto import (
    AnalyticsBucket,
    AnalyticsExportRow,
    AnalyticsGroupBy,
    AnalyticsLotRef,
    AnalyticsRental,
    AnalyticsSummary,
)
from src.application.dtos.verification_dto import AdminUserRef
from src.domain.value_objects.time_range import TimeRange

# Keep the predicate and range expression aligned with the partial GiST index.
_REVENUE_STATUSES = "('active', 'overdue', 'completed')"
_RENTAL_RANGE = "tstzrange(r.start_time, r.end_time, '[)')"
_IN_PERIOD = "r.start_time >= :starts AND r.start_time < :ends"
_UTILIZATION = """
    COALESCE(
        ROUND(100 * occupied_seconds / NULLIF(available_seconds, 0), 1), 0
    ) AS utilization_pct
"""
_PERIOD_SECONDS = "EXTRACT(EPOCH FROM CAST(:ends AS timestamptz) - CAST(:starts AS timestamptz))"


def _scoped_lots(filter_lot: bool, filter_category: bool) -> str:
    lot_filter = "AND id = :lot_id" if filter_lot else ""
    category_filter = "AND category_id = :category_id" if filter_category else ""
    return f"""
    SELECT id, name, category_id, status
    FROM lot
    WHERE tenant_id = :tenant_id {lot_filter} {category_filter}
    """


def _report_rows(filter_lot: bool, filter_category: bool) -> str:
    lot_filter = "AND r.lot_id = :lot_id" if filter_lot else ""
    category_filter = "AND r.lot_id IN (SELECT id FROM scoped_lots)" if filter_category else ""
    return f"""
    SELECT r.lot_id, r.start_time, LEAST(r.end_time, :ends) AS end_time, r.status,
           r.price_minor, true AS incurred
    FROM rental r
    WHERE r.tenant_id = :tenant_id {lot_filter} {category_filter} AND {_IN_PERIOD}

    UNION ALL

    SELECT r.lot_id, r.start_time, LEAST(r.end_time, :ends), r.status,
           0 AS price_minor, false AS incurred
    FROM rental r
    WHERE r.tenant_id = :tenant_id {lot_filter} {category_filter} AND r.start_time < :starts
      AND r.status IN {_REVENUE_STATUSES}
      AND {_RENTAL_RANGE} && tstzrange(:starts, :ends, '[)')
    """


# Earlier completions can overlap subsequent rentals. Union each lot's clipped
# rental periods before adding their lengths to the fleet's occupied time.
_OCCUPIED_RANGES = f"""
    range_agg(tstzrange(GREATEST(:starts, r.start_time), r.end_time, '[)'))
        FILTER (WHERE r.status IN {_REVENUE_STATUSES}) AS occupied
"""
_FINANCIAL_COLUMNS = f"""
    COALESCE(SUM(r.price_minor) FILTER (
        WHERE r.incurred AND r.status IN {_REVENUE_STATUSES}
    ), 0) AS revenue_minor,
    COUNT(*) FILTER (WHERE r.incurred) AS rentals_count,
    COUNT(*) FILTER (WHERE r.incurred AND r.status = 'cancelled') AS cancelled_count,
    COUNT(*) FILTER (WHERE r.incurred AND r.status = 'overdue') AS overdue_count
"""


def _totals_query(
    group_by: AnalyticsGroupBy | None, *, filter_lot: bool, filter_category: bool = False
) -> TextClause:
    if group_by == "lot":
        metrics = f"""
        SELECT id AS key, name AS label, revenue_minor, rentals_count, cancelled_count,
               overdue_count, occupied_seconds,
               CASE WHEN status != 'archived' THEN {_PERIOD_SECONDS} ELSE 0 END
                   AS available_seconds
        FROM lot_metrics
        """
    else:
        # Group over the catalog so an empty fleet/category still has a zero report.
        category = group_by == "category"
        key = "c.id AS key, c.name AS label," if category else ""
        category_filter = "AND c.id = :category_id " if filter_category else ""
        source = (
            "category c LEFT JOIN lot_metrics m ON m.category_id = c.id "
            f"WHERE c.tenant_id = :tenant_id {category_filter}GROUP BY c.id, c.name"
            if category
            else "lot_metrics m"
        )
        metrics = f"""
        SELECT {key}
            COALESCE(SUM(m.revenue_minor), 0) AS revenue_minor,
            COALESCE(SUM(m.rentals_count), 0) AS rentals_count,
            COALESCE(SUM(m.cancelled_count), 0) AS cancelled_count,
            COALESCE(SUM(m.overdue_count), 0) AS overdue_count,
            COALESCE(SUM(m.occupied_seconds), 0) AS occupied_seconds,
            COUNT(m.id) FILTER (WHERE m.status != 'archived') * {_PERIOD_SECONDS}
                AS available_seconds
        FROM {source}
        """
    ordering = "ORDER BY revenue_minor DESC, label, key" if group_by is not None else ""
    return text(f"""
        WITH scoped_lots AS ({_scoped_lots(filter_lot, filter_category)}),
        report_rows AS ({_report_rows(filter_lot, filter_category)}),
        totals AS (
            SELECT r.lot_id, {_FINANCIAL_COLUMNS}, {_OCCUPIED_RANGES}
            FROM report_rows r
            GROUP BY r.lot_id
        ),
        lot_metrics AS (
            SELECT l.id, l.name, l.category_id, l.status,
                   COALESCE(t.revenue_minor, 0) AS revenue_minor,
                   COALESCE(t.rentals_count, 0) AS rentals_count,
                   COALESCE(t.cancelled_count, 0) AS cancelled_count,
                   COALESCE(t.overdue_count, 0) AS overdue_count,
                   COALESCE(u.seconds, 0) AS occupied_seconds
            FROM scoped_lots l
            LEFT JOIN totals t ON t.lot_id = l.id
            LEFT JOIN LATERAL (
                SELECT EXTRACT(EPOCH FROM SUM(upper(segment) - lower(segment))) AS seconds
                FROM unnest(t.occupied) AS segment
                WHERE l.status != 'archived'
            ) u ON true
        ),
        metrics AS ({metrics})
        SELECT *, {_UTILIZATION}
        FROM metrics
        {ordering}
    """)


def _daily_query(*, filter_lot: bool, filter_category: bool = False) -> TextClause:
    # At a repeated midnight PostgreSQL resolves the civil time to its later fold.
    # Test the previous day's offset too, then use the earliest valid midnight.
    return text(f"""
        WITH scoped_lots AS ({_scoped_lots(filter_lot, filter_category)}),
        settings AS (
            SELECT timezone AS tz FROM tenant WHERE id = :tenant_id
        ),
        midnights AS (
            SELECT s.tz, local_midnight,
                   timezone(s.tz, local_midnight) AS midnight,
                   timezone(s.tz, local_midnight - interval '1 day') + interval '24 hours'
                       AS previous_offset_midnight
            FROM settings s
            CROSS JOIN LATERAL generate_series(
                timezone(s.tz, CAST(:starts AS timestamptz))::date::timestamp,
                timezone(s.tz, CAST(:ends AS timestamptz) - interval '1 microsecond')::date
                    + interval '1 day',
                interval '1 day'
            ) AS local_midnight
        ),
        day_starts AS (
            SELECT local_midnight::date AS day,
                   CASE WHEN timezone(tz, previous_offset_midnight) = local_midnight
                        THEN LEAST(midnight, previous_offset_midnight)
                        ELSE midnight END AS midnight
            FROM midnights
        ),
        day_bounds AS (
            SELECT day, midnight, LEAD(midnight) OVER (ORDER BY day) AS next_midnight
            FROM day_starts
        ),
        days AS (
            SELECT day, GREATEST(:starts, midnight) AS starts, LEAST(:ends, next_midnight) AS ends
            FROM day_bounds
            WHERE next_midnight IS NOT NULL
        ),
        report_rows AS ({_report_rows(filter_lot, filter_category)}),
        financial AS (
            SELECT timezone(s.tz, r.start_time)::date AS day, {_FINANCIAL_COLUMNS}
            FROM report_rows r
            CROSS JOIN settings s
            WHERE r.incurred
            GROUP BY 1
        ),
        fleet AS (
            SELECT COUNT(*) AS lots FROM scoped_lots WHERE status != 'archived'
        ),
        coverage AS (
            SELECT r.lot_id, {_OCCUPIED_RANGES}
            FROM report_rows r
            WHERE r.status IN {_REVENUE_STATUSES}
            GROUP BY r.lot_id
        ),
        occupied_ranges AS (
            SELECT lower(segment) AS starts, upper(segment) AS ends, COUNT(*) AS lots
            FROM coverage u
            JOIN scoped_lots l ON l.id = u.lot_id AND l.status != 'archived'
            CROSS JOIN LATERAL unnest(u.occupied) AS segment
            GROUP BY 1, 2
        ),
        segments AS (
            SELECT u.*, timezone(s.tz, u.starts)::date AS first_day,
                   timezone(s.tz, u.ends - interval '1 microsecond')::date AS last_day
            FROM occupied_ranges u
            CROSS JOIN settings s
        ),
        usage AS (
            SELECT d.day, EXTRACT(EPOCH FROM SUM(
                (LEAST(d.ends, u.ends) - GREATEST(d.starts, u.starts)) * u.lots
            )) AS seconds
            FROM segments u
            CROSS JOIN LATERAL generate_series(0, u.last_day - u.first_day) AS shift
            JOIN days d ON d.day = u.first_day + shift
            WHERE d.starts < u.ends AND u.starts < d.ends AND d.starts < d.ends
            GROUP BY d.day
        ),
        metrics AS (
            SELECT d.day AS key, d.day AS label,
                   COALESCE(f.revenue_minor, 0) AS revenue_minor,
                   COALESCE(f.rentals_count, 0) AS rentals_count,
                   COALESCE(f.cancelled_count, 0) AS cancelled_count,
                   COALESCE(u.seconds, 0) AS occupied_seconds,
                   fleet.lots * EXTRACT(EPOCH FROM d.ends - d.starts) AS available_seconds
            FROM days d
            CROSS JOIN fleet
            LEFT JOIN financial f ON f.day = d.day
            LEFT JOIN usage u ON u.day = d.day
            WHERE d.starts < d.ends
        )
        SELECT *, {_UTILIZATION}
        FROM metrics
        ORDER BY key
    """)


def _bucket(row: RowMapping) -> AnalyticsBucket:
    return AnalyticsBucket(
        key=str(row.key),
        label=str(row.label),
        revenue_minor=int(row.revenue_minor),
        rentals_count=int(row.rentals_count),
        cancelled_count=int(row.cancelled_count),
        utilization_pct=float(row.utilization_pct),
    )


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    def _params(
        self, period: TimeRange, lot_id: UUID | None = None, category_id: UUID | None = None
    ) -> dict[str, object]:
        params: dict[str, object] = {
            "tenant_id": self._tenant_id,
            "starts": period.start,
            "ends": period.end,
        }
        if lot_id is not None:
            params["lot_id"] = lot_id
        if category_id is not None:
            params["category_id"] = category_id
        return params

    async def summary(
        self, period: TimeRange, *, lot_id: UUID | None = None, category_id: UUID | None = None
    ) -> AnalyticsSummary:
        result = await self._session.execute(
            _totals_query(
                None, filter_lot=lot_id is not None, filter_category=category_id is not None
            ),
            self._params(period, lot_id, category_id),
        )
        row = result.mappings().one()
        revenue = int(row.revenue_minor)
        rentals = int(row.rentals_count)
        cancelled = int(row.cancelled_count)
        non_cancelled = rentals - cancelled
        # Keep the entire minor-unit calculation exact even above the float precision limit.
        average = (2 * revenue + non_cancelled) // (2 * non_cancelled) if non_cancelled else 0
        return AnalyticsSummary(
            period_from=period.start,
            period_to=period.end,
            revenue_minor=revenue,
            rentals_count=rentals,
            cancelled_count=cancelled,
            overdue_count=int(row.overdue_count),
            avg_rental_minor=average,
            utilization_pct=float(row.utilization_pct),
        )

    async def buckets(
        self,
        period: TimeRange,
        group_by: AnalyticsGroupBy,
        *,
        lot_id: UUID | None = None,
        category_id: UUID | None = None,
    ) -> list[AnalyticsBucket]:
        query = (
            _daily_query(filter_lot=lot_id is not None, filter_category=category_id is not None)
            if group_by == "day"
            else _totals_query(
                group_by, filter_lot=lot_id is not None, filter_category=category_id is not None
            )
        )
        result = await self._session.execute(query, self._params(period, lot_id, category_id))
        return [_bucket(row) for row in result.mappings()]

    async def lot(self, lot_id: UUID) -> AnalyticsLotRef | None:
        result = await self._session.execute(
            text("SELECT id, name FROM lot WHERE tenant_id = :tenant_id AND id = :lot_id"),
            {"tenant_id": self._tenant_id, "lot_id": lot_id},
        )
        row = result.mappings().one_or_none()
        return AnalyticsLotRef(id=row.id, name=row.name) if row is not None else None

    async def rentals(
        self, period: TimeRange, lot_id: UUID, *, limit: int, offset: int
    ) -> list[AnalyticsRental]:
        result = await self._session.execute(
            text(f"""
                SELECT r.id, r.start_time, r.end_time, r.status, r.price_minor, r.currency,
                       u.id AS user_id, u.name AS user_name, u.email AS user_email
                FROM rental r
                JOIN "user" u ON u.tenant_id = r.tenant_id AND u.id = r.user_id
                WHERE r.tenant_id = :tenant_id AND r.lot_id = :lot_id AND {_IN_PERIOD}
                ORDER BY r.start_time DESC, r.id DESC
                LIMIT :limit OFFSET :offset
            """),
            {**self._params(period, lot_id), "limit": limit, "offset": offset},
        )
        return [
            AnalyticsRental(
                id=row.id,
                start_time=row.start_time,
                end_time=row.end_time,
                status=row.status,
                price_minor=int(row.price_minor),
                currency=row.currency,
                user=AdminUserRef(id=row.user_id, name=row.user_name, email=row.user_email),
            )
            for row in result.mappings()
        ]

    async def iter_export(self, period: TimeRange) -> AsyncGenerator[AnalyticsExportRow]:
        result = await self._session.stream(
            text(f"""
                SELECT r.id, l.name AS lot_name, c.name AS category_name,
                       r.start_time, r.end_time, r.status, r.price_minor, r.currency
                FROM rental r
                JOIN lot l ON l.tenant_id = r.tenant_id AND l.id = r.lot_id
                JOIN category c ON c.tenant_id = l.tenant_id AND c.id = l.category_id
                WHERE r.tenant_id = :tenant_id AND {_IN_PERIOD}
                ORDER BY r.start_time, r.id
            """),
            self._params(period),
            execution_options={"yield_per": 1000},
        )
        try:
            async for row in result.mappings():
                yield AnalyticsExportRow(
                    id=row.id,
                    lot_name=row.lot_name,
                    category_name=row.category_name,
                    start_time=row.start_time,
                    end_time=row.end_time,
                    status=row.status,
                    price_minor=int(row.price_minor),
                    currency=row.currency,
                )
        finally:
            with CancelScope(shield=True):
                await result.close()
