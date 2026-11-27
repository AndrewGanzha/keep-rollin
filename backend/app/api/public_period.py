from datetime import UTC, datetime

from fastapi import HTTPException

from src.domain.exceptions import InvalidTimeRangeError
from src.domain.value_objects.time_range import TimeRange

MAX_AVAILABILITY_DAYS = 90


def _utc_bound(value: datetime, field: str) -> datetime:
    try:
        return value.astimezone(UTC)
    except OverflowError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {field: "must be representable in UTC"},
            },
        ) from exc


def parse_public_period(
    from_: datetime,
    to: datetime,
    *,
    max_days: int | None = None,
    from_field: str = "from",
    to_field: str = "to",
    normalize_to_utc: bool = False,
) -> TimeRange:
    if (
        from_.tzinfo is None
        or from_.utcoffset() is None
        or to.tzinfo is None
        or to.utcoffset() is None
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {from_field: "must be timezone-aware"},
            },
        )
    if normalize_to_utc:
        from_ = _utc_bound(from_, from_field)
        to = _utc_bound(to, to_field)
    try:
        period = TimeRange(from_, to)
    except InvalidTimeRangeError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {to_field: "must be after from"},
            },
        ) from exc
    if max_days is not None and period.duration_seconds > max_days * 86400:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "fields": {to_field: f"range must not exceed {max_days} days"},
            },
        )
    return period
