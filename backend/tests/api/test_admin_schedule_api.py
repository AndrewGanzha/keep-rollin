import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import create_engine, create_session_factory
from app.models import Tenant, User
from src.infrastructure.postgres.models.battery_stock_record import BatteryStockRecord
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord, RentalStatus
from tests.api.test_admin_calendar_api import (
    DATABASE_URL,
    SeededCalendarAPI,
    auth,
    cleanup_calendar,
    client_for,
    login,
    seed_calendar,
)

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")
SCHEDULE = "/api/v1/admin/schedule"
WINDOW = {"from": "2025-10-26", "to": "2025-10-27"}
# The fall DST transition makes this Berlin civil day 25 hours long.
WINDOW_START = datetime(2025, 10, 25, 22, tzinfo=UTC)
WINDOW_END = datetime(2025, 10, 26, 23, tzinfo=UTC)
HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class ScheduleFixture:
    calendar: SeededCalendarAPI
    empty_lot_id: UUID
    hour_lot_id: UUID
    hour_category_id: UUID
    foreign_category_id: UUID
    completed_id: UUID
    booked_id: UUID
    overdue_id: UUID
    block_id: UUID
    foreign_block_id: UUID


def _rental(
    session: AsyncSession,
    calendar: SeededCalendarAPI,
    lot_id: UUID,
    user_id: UUID,
    start: datetime,
    end: datetime,
    status: RentalStatus,
    *,
    batteries: int = 0,
) -> UUID:
    rental_id, occupancy_id = uuid4(), uuid4()
    session.add_all(
        [
            OccupancyRecord(
                id=occupancy_id,
                tenant_id=calendar.tenant_a,
                lot_id=lot_id,
                kind="booking",
                period=Range(start, end, bounds="[)"),
                ref_id=rental_id,
                status="released" if status in ("completed", "cancelled") else "active",
            ),
            RentalRecord(
                id=rental_id,
                tenant_id=calendar.tenant_a,
                user_id=user_id,
                lot_id=lot_id,
                occupancy_id=occupancy_id,
                variant_id=uuid4(),
                start_time=start,
                end_time=end,
                cancellation_deadline=start,
                battery_type="48v" if batteries else None,
                battery_count=batteries,
                price_minor=19000,
                currency="RUB",
                status=status,
            ),
        ]
    )
    return rental_id


def _lot(
    calendar: SeededCalendarAPI, category_id: UUID, name: str, *, hourly: bool = False
) -> LotRecord:
    lot_id = uuid4()
    return LotRecord(
        id=lot_id,
        tenant_id=calendar.tenant_a,
        category_id=category_id,
        slug=f"schedule-{lot_id.hex}",
        name=name,
        rental_unit="hour" if hourly else "day",
        battery_type="48v" if hourly else None,
        allowed_durations=[1],
        status="active" if hourly else "archived",
    )


def _block(
    tenant_id: UUID,
    lot_id: UUID,
    start: datetime,
    end: datetime,
    *,
    reason: str,
    status: str = "active",
    kind: str = "block",
) -> OccupancyRecord:
    return OccupancyRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        lot_id=lot_id,
        period=Range(start, end, bounds="[)"),
        kind=kind,
        status=status,
        reason=reason,
    )


async def _seed_schedule(calendar: SeededCalendarAPI) -> ScheduleFixture:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    try:
        async with create_session_factory(engine)() as session:
            await session.execute(
                update(Tenant)
                .where(Tenant.id == calendar.tenant_a)
                .values(timezone="Europe/Berlin")
            )
            rider_id = await session.scalar(
                update(User)
                .where(User.tenant_id == calendar.tenant_a, User.email == calendar.user_a_email)
                .values(name="Current rider name", phone="+79991234567")
                .returning(User.id)
            )
            foreign_category_id = await session.scalar(
                select(LotRecord.category_id).where(LotRecord.id == calendar.lot_b_id)
            )
            assert rider_id is not None and foreign_category_id is not None

            hour_category = CategoryRecord(
                id=uuid4(), tenant_id=calendar.tenant_a, name="Hourly", slug="schedule-hourly"
            )
            session.add(hour_category)
            await session.flush()
            empty_lot = _lot(calendar, calendar.category_a_id, "Empty lot")
            hour_lot = _lot(calendar, hour_category.id, "Hourly lot", hourly=True)
            session.add_all([empty_lot, hour_lot])
            session.add_all(
                [
                    BatteryStockRecord(
                        tenant_id=calendar.tenant_a, battery_type="48v", name="48 V", quantity=8
                    ),
                    BatteryStockRecord(
                        tenant_id=calendar.tenant_b,
                        battery_type="foreign",
                        name="Foreign stock",
                        quantity=10,
                    ),
                ]
            )
            await session.flush()

            completed_id = _rental(
                session,
                calendar,
                calendar.lot_a_id,
                rider_id,
                WINDOW_START - HOUR,
                WINDOW_START + HOUR,
                "completed",
                batteries=3,
            )
            booked_id = _rental(
                session,
                calendar,
                calendar.lot_a_id,
                rider_id,
                WINDOW_START + 4 * HOUR,
                WINDOW_START + 5 * HOUR,
                "booked",
            )
            overdue_id = _rental(
                session,
                calendar,
                calendar.lot_a_id,
                rider_id,
                WINDOW_END - HOUR,
                WINDOW_END + 2 * HOUR,
                "overdue",
            )
            boundary_cases: tuple[tuple[datetime, datetime, RentalStatus], ...] = (
                (WINDOW_START - 2 * HOUR, WINDOW_START, "completed"),
                (WINDOW_END, WINDOW_END + HOUR, "completed"),
                (WINDOW_START + HOUR, WINDOW_START + 2 * HOUR, "cancelled"),
            )
            for start, end, state in boundary_cases:
                _rental(session, calendar, calendar.lot_a_id, rider_id, start, end, state)
            future = datetime.now(UTC) + timedelta(days=7)
            _rental(
                session,
                calendar,
                hour_lot.id,
                rider_id,
                future,
                future + HOUR,
                "booked",
                batteries=2,
            )
            block = _block(
                calendar.tenant_a,
                hour_lot.id,
                WINDOW_START - timedelta(days=1),
                WINDOW_END,
                reason="Scheduled repair",
            )
            foreign_block = _block(
                calendar.tenant_b,
                calendar.lot_b_id,
                WINDOW_START,
                WINDOW_END,
                reason="Foreign repair",
            )
            session.add_all(
                [
                    block,
                    foreign_block,
                    _block(
                        calendar.tenant_a,
                        hour_lot.id,
                        WINDOW_START,
                        WINDOW_END,
                        reason="Released block",
                        status="released",
                    ),
                    _block(
                        calendar.tenant_a,
                        calendar.lot_a_id,
                        WINDOW_START + 2 * HOUR,
                        WINDOW_START + 3 * HOUR,
                        reason="Implicit maintenance",
                        kind="maintenance",
                    ),
                    _block(
                        calendar.tenant_a,
                        hour_lot.id,
                        WINDOW_END,
                        WINDOW_END + HOUR,
                        reason="Touches exclusive end",
                    ),
                ]
            )
            await session.commit()
            return ScheduleFixture(
                calendar,
                empty_lot.id,
                hour_lot.id,
                hour_category.id,
                foreign_category_id,
                completed_id,
                booked_id,
                overdue_id,
                block.id,
                foreign_block.id,
            )
    finally:
        await engine.dispose()


@pytest.fixture
def schedule() -> Iterator[ScheduleFixture]:
    calendar = seed_calendar()
    try:
        yield asyncio.run(_seed_schedule(calendar))
    finally:
        cleanup_calendar((calendar.tenant_a, calendar.tenant_b))


def test_schedule_returns_tenant_civil_day_intervals_and_empty_lots(
    schedule: ScheduleFixture,
) -> None:
    calendar = schedule.calendar
    with client_for(calendar.domain_a) as client:
        headers = auth(login(client, calendar.owner_a_email))
        response = client.get(SCHEDULE, headers=headers, params=WINDOW)
        stock = client.get("/api/v1/admin/batteries", headers=headers)
        filtered = client.get(
            SCHEDULE, headers=headers, params={**WINDOW, "category_id": str(calendar.category_a_id)}
        )
        old = client.get(
            "/api/v1/admin/calendar",
            headers=headers,
            params={"from": WINDOW_START.isoformat(), "to": WINDOW_END.isoformat()},
        )

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()
    lots = {item["id"]: item for item in data["lots"]}
    assert set(lots) == {
        str(calendar.lot_a_id),
        str(schedule.hour_lot_id),
        str(schedule.empty_lot_id),
    }
    assert lots[str(schedule.hour_lot_id)] == {
        "id": str(schedule.hour_lot_id),
        "name": "Hourly lot",
        "category_id": str(schedule.hour_category_id),
        "status": "active",
        "battery_type": "48v",
        "rental_unit": "hour",
    }
    assert lots[str(schedule.empty_lot_id)]["status"] == "archived"
    intervals = {item["id"]: item for item in data["intervals"]}
    assert set(intervals) == {
        str(schedule.completed_id),
        str(schedule.booked_id),
        str(schedule.overdue_id),
        str(schedule.block_id),
    }
    completed = intervals[str(schedule.completed_id)]
    completed_start = datetime.fromisoformat(completed.pop("start_time"))
    completed_end = datetime.fromisoformat(completed.pop("end_time"))
    assert completed_start == WINDOW_START
    assert completed_end == WINDOW_START + HOUR
    assert completed == {
        "id": str(schedule.completed_id),
        "lot_id": str(calendar.lot_a_id),
        "kind": "rental",
        "rental_id": str(schedule.completed_id),
        "status": "completed",
        "battery_count": 3,
        "user_name": "Current rider name",
        "clipped_start": True,
        "clipped_end": False,
    }
    booked = intervals[str(schedule.booked_id)]
    assert booked["status"] == "booked"
    assert not booked["clipped_start"] and not booked["clipped_end"]
    overdue = intervals[str(schedule.overdue_id)]
    assert overdue["status"] == "overdue"
    assert datetime.fromisoformat(overdue["start_time"]) == WINDOW_END - HOUR
    assert datetime.fromisoformat(overdue["end_time"]) == WINDOW_END
    assert not overdue["clipped_start"] and overdue["clipped_end"]
    block = intervals[str(schedule.block_id)]
    assert block["kind"] == "block"
    assert block["block_id"] == str(schedule.block_id)
    assert block["reason"] == "Scheduled repair"
    assert datetime.fromisoformat(block["start_time"]) == WINDOW_START - timedelta(days=1)
    assert datetime.fromisoformat(block["end_time"]) == WINDOW_END
    assert block["clipped_start"] and not block["clipped_end"]

    assert stock.status_code == 200, stock.text
    assert (
        data["battery_stock"]
        == stock.json()
        == [{"battery_type": "48v", "name": "48 V", "quantity": 8, "peak_committed": 2}]
    )
    assert filtered.status_code == 200, filtered.text
    assert {item["id"] for item in filtered.json()["lots"]} == {
        str(calendar.lot_a_id),
        str(schedule.empty_lot_id),
    }
    assert len(filtered.json()["intervals"]) == 3
    assert all(item["lot_id"] == str(calendar.lot_a_id) for item in filtered.json()["intervals"])
    assert filtered.json()["battery_stock"] == data["battery_stock"]

    assert old.status_code == 200, old.text
    assert old.headers["Cache-Control"] == "no-store"
    legacy_event = next(
        item for item in old.json() if item["rental_id"] == str(schedule.overdue_id)
    )
    assert legacy_event["kind"] == "booking"
    assert datetime.fromisoformat(legacy_event["end_time"]) == WINDOW_END + 2 * HOUR


def test_schedule_permissions_and_category_filters_are_tenant_scoped(
    schedule: ScheduleFixture,
) -> None:
    calendar = schedule.calendar
    with client_for(calendar.domain_a) as client:
        assert client.get(SCHEDULE, params=WINDOW).status_code == 401
        rider = auth(login(client, calendar.user_a_email))
        assert client.get(SCHEDULE, params=WINDOW, headers=rider).status_code == 403
        admin = auth(login(client, calendar.admin_a_email))
        granted = client.get(SCHEDULE, params=WINDOW, headers=admin)
        foreign_category = client.get(
            SCHEDULE,
            params={**WINDOW, "category_id": str(schedule.foreign_category_id)},
            headers=admin,
        )
    assert granted.status_code == 200, granted.text
    assert granted.headers["Cache-Control"] == "no-store"
    assert foreign_category.status_code == 200, foreign_category.text
    assert foreign_category.json() == {
        "lots": [],
        "intervals": [],
        "battery_stock": granted.json()["battery_stock"],
    }

    with client_for(calendar.domain_b) as client:
        other = client.get(
            SCHEDULE, params=WINDOW, headers=auth(login(client, calendar.owner_b_email))
        )
    assert other.status_code == 200, other.text
    assert [lot["id"] for lot in other.json()["lots"]] == [str(calendar.lot_b_id)]
    assert [interval["id"] for interval in other.json()["intervals"]] == [
        str(schedule.foreign_block_id)
    ]
    assert [item["battery_type"] for item in other.json()["battery_stock"]] == ["foreign"]
    assert "Current rider name" not in other.text


def test_schedule_validates_strict_dates_and_civil_day_window(schedule: ScheduleFixture) -> None:
    calendar = schedule.calendar
    with client_for(calendar.domain_a) as client:
        headers = auth(login(client, calendar.owner_a_email))
        exact_limit = client.get(
            SCHEDULE, params={"from": "2025-09-01", "to": "2025-11-30"}, headers=headers
        )
        assert exact_limit.status_code == 200, exact_limit.text
        invalid = [
            ({"to": "2025-10-27"}, "from"),
            ({**WINDOW, "from": "2025-10-26T00:00:00Z"}, "from"),
            ({**WINDOW, "from": "1761436800"}, "from"),
            ({**WINDOW, "from": "2025-9-01"}, "from"),
            ({**WINDOW, "from": "2025-02-29"}, "from"),
            ({**WINDOW, "to": "2025-10-26"}, "to"),
            ({**WINDOW, "to": "2025-10-25"}, "to"),
            ({"from": "2025-09-01", "to": "2025-12-01"}, "to"),
            ({"from": "0001-01-01", "to": "0001-01-02"}, "from"),
            ({**WINDOW, "category_id": "invalid"}, "category_id"),
        ]
        for query, field in invalid:
            response = client.get(SCHEDULE, params=query, headers=headers)
            assert response.status_code == 422, (query, response.text)
            assert response.headers["Cache-Control"] == "no-store"
            assert response.json()["code"] == "validation_error"
            assert field in response.json()["fields"]
