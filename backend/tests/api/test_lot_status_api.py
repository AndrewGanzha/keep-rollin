from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import configure_session, create_engine, create_session_factory
from app.models import User
from src.application.services.audit import AuditEntry
from src.application.services.occupancy import OccupancyService
from src.domain.exceptions import LotUnavailableError
from src.domain.value_objects.time_range import TimeRange
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.repositories.audit_repository import AuditRepository
from src.infrastructure.postgres.repositories.occupancy_repository import OccupancyRepository
from tests.api.test_admin_categories_api import (
    DATABASE_URL,
    SeededAdminCategories,
    auth,
    client_for,
    login,
)
from tests.api.test_admin_lots_api import LOTS, create_lot
from tests.api.test_admin_lots_api import seeded as seeded

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
STATUS_ACTION = "lot.status_changed"


@dataclass(frozen=True)
class OwnerLot:
    client: TestClient
    headers: dict[str, str]
    initial: dict[str, object]
    tenant_id: UUID

    @property
    def id(self) -> UUID:
        return UUID(str(self.initial["id"]))

    @property
    def url(self) -> str:
        return f"{LOTS}/{self.id}"

    def transition(self, target: str) -> Response:
        return cast(
            Response,
            self.client.post(f"{self.url}/status", headers=self.headers, json={"status": target}),
        )

    def detail(self) -> dict[str, object]:
        response = self.client.get(self.url, headers=self.headers)
        assert response.status_code == 200, response.text
        value: dict[str, object] = response.json()
        return value


@pytest.fixture
def lot(seeded: SeededAdminCategories) -> Iterator[OwnerLot]:
    with client_for(seeded.domain_a) as client:
        headers = auth(login(client, seeded.owner_a_email))
        initial = create_lot(client, headers, seeded.active_category_id)
        yield OwnerLot(client, headers, initial, seeded.tenant_a)


@asynccontextmanager
async def db_session(tenant_id: UUID | None = None) -> AsyncIterator[AsyncSession]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            if tenant_id is not None:
                configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_app")
            yield session
    finally:
        await engine.dispose()


async def status_audit(lot: OwnerLot) -> list[AuditLogRecord]:
    async with db_session(lot.tenant_id) as session:
        entries = await session.scalars(
            select(AuditLogRecord)
            .where(AuditLogRecord.entity_id == lot.id, AuditLogRecord.action == STATUS_ACTION)
            .order_by(AuditLogRecord.created_at, AuditLogRecord.id)
        )
        return list(entries)


async def occupancies(lot: OwnerLot) -> dict[UUID, OccupancyRecord]:
    async with db_session(lot.tenant_id) as session:
        records = await session.scalars(
            select(OccupancyRecord).where(OccupancyRecord.lot_id == lot.id)
        )
        return {record.id: record for record in records}


def assert_problem(response: Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code, response.text
    assert response.json()["code"] == code


def period_params(start: datetime, end: datetime) -> dict[str, str]:
    return {"from": start.isoformat(), "to": end.isoformat()}


def test_status_requires_owner_csrf_and_same_tenant(
    lot: OwnerLot, seeded: SeededAdminCategories
) -> None:
    url = f"{lot.url}/status"
    payload = {"status": "archived"}
    assert lot.client.post(url, json=payload).status_code == 401

    for email in (seeded.admin_a_email, seeded.user_a_email):
        headers = auth(login(lot.client, email))
        assert lot.client.post(url, headers=headers, json=payload).status_code == 403

    with client_for(seeded.domain_a, browser_headers=False) as bare:
        assert bare.post(url, headers=lot.headers, json=payload).status_code == 403

    with client_for(seeded.domain_b) as foreign:
        headers = auth(login(foreign, seeded.owner_b_email))
        assert_problem(foreign.post(url, headers=headers, json=payload), 404, "not_found")

    for invalid in ({"status": "overdue"}, {"status": "archived", "version": 1}, {}):
        response = lot.client.post(url, headers=lot.headers, json=invalid)
        assert response.status_code == 422, response.text

    assert lot.detail() == lot.initial
    assert asyncio.run(status_audit(lot)) == []

    archived = lot.transition("archived")
    assert archived.status_code == 200, archived.text
    assert archived.headers["Cache-Control"] == "no-store"
    expected = lot.initial | {"status": "archived", "version": 2, "is_bookable": False}
    assert archived.json() == expected
    repeated = lot.transition("archived")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == expected
    assert lot.detail() == expected
    stale = lot.client.patch(lot.url, headers=lot.headers, json={"version": 1, "name": "Stale"})
    assert_problem(stale, 409, "stale_version")

    (entry,) = asyncio.run(status_audit(lot))
    assert entry.actor_id is not None
    assert entry.actor_role == "owner"
    assert entry.entity_type == "lot"
    assert entry.metadata_json == {"old_status": "active", "new_status": "archived"}
    assert entry.request_id == archived.headers["X-Request-Id"]


def test_owner_cannot_manually_leave_overdue(lot: OwnerLot) -> None:
    async def seed_overdue() -> None:
        async with db_session() as session:
            await session.execute(
                update(LotRecord).where(LotRecord.id == lot.id).values(status="overdue")
            )
            await session.commit()

    asyncio.run(seed_overdue())
    for target in ("active", "archived", "maintenance"):
        assert_problem(lot.transition(target), 409, "lot_unavailable")

    assert lot.detail()["status"] == "overdue"
    assert lot.detail()["version"] == 1
    assert asyncio.run(occupancies(lot)) == {}
    assert asyncio.run(status_audit(lot)) == []


@pytest.mark.parametrize("offset_hours", [-2, -1, 1], ids=["past", "current", "future"])
def test_unreleased_booking_blocks_archive_and_maintenance(
    lot: OwnerLot, offset_hours: int
) -> None:
    now = datetime.now(UTC)
    start = now + timedelta(hours=offset_hours)
    end = start + timedelta(hours=1 if offset_hours != -1 else 2)

    async def reserve() -> UUID:
        async with db_session(lot.tenant_id) as session:
            booking = await OccupancyService(OccupancyRepository(session)).reserve(
                lot_id=lot.id, kind="booking", period=TimeRange(start, end), ref_id=uuid4()
            )
            await session.commit()
            return booking.id

    async def release(booking_id: UUID) -> None:
        async with db_session(lot.tenant_id) as session:
            assert await OccupancyRepository(session).release(booking_id)
            await session.commit()

    booking_id = asyncio.run(reserve())
    for target in ("archived", "maintenance"):
        assert_problem(lot.transition(target), 409, "lot_has_active_rental")

    assert lot.detail() == lot.initial
    records = asyncio.run(occupancies(lot))
    assert set(records) == {booking_id}
    assert records[booking_id].status == "active"
    assert asyncio.run(status_audit(lot)) == []

    asyncio.run(release(booking_id))
    assert lot.transition("maintenance").status_code == 200
    assert lot.transition("archived").status_code == 200
    assert asyncio.run(occupancies(lot))[booking_id].status == "released"


@pytest.mark.parametrize("target", ["active", "archived"])
def test_indefinite_maintenance_hides_lot_projects_calendar_and_preserves_history(
    lot: OwnerLot, seeded: SeededAdminCategories, target: str
) -> None:
    now = datetime.now(UTC)
    past = Range(now - timedelta(days=4), now - timedelta(days=3), bounds="[)")
    released = Range(now - timedelta(days=2), None, bounds="[)")
    past_id, released_id = uuid4(), uuid4()

    async def seed_history() -> UUID:
        async with db_session() as session:
            owner_id = await session.scalar(
                select(User.id).where(
                    User.tenant_id == lot.tenant_id, User.email == seeded.owner_a_email
                )
            )
            assert owner_id is not None
            session.add_all(
                [
                    OccupancyRecord(
                        id=past_id,
                        tenant_id=lot.tenant_id,
                        lot_id=lot.id,
                        kind="maintenance",
                        period=past,
                        status="active",
                        ref_id=lot.id,
                        created_by=owner_id,
                    ),
                    OccupancyRecord(
                        id=released_id,
                        tenant_id=lot.tenant_id,
                        lot_id=lot.id,
                        kind="maintenance",
                        period=released,
                        status="released",
                        ref_id=lot.id,
                        created_by=owner_id,
                    ),
                ]
            )
            await session.commit()
            return owner_id

    owner_id = asyncio.run(seed_history())
    window = TimeRange(now + timedelta(hours=1), now + timedelta(hours=2))
    params = period_params(window.start, window.end)
    public_list = "/api/v1/public/lots"
    public_detail = f"{public_list}/{lot.initial['slug']}"
    public_summary = "/api/v1/public/availability"

    def assert_public_visibility(visible: bool, lots_total: int) -> None:
        page = lot.client.get(public_list)
        assert page.status_code == 200, page.text
        assert (str(lot.id) in {item["id"] for item in page.json()["items"]}) is visible
        expected_status = 200 if visible else 404
        assert lot.client.get(public_detail).status_code == expected_status
        assert lot.client.get(f"{public_detail}/availability", params=params).status_code == (
            expected_status
        )
        total = lot.client.get(public_summary, params=params)
        assert total.status_code == 200, total.text
        assert total.json()["lots_total"] == lots_total

    baseline = lot.client.get(public_summary, params=params)
    assert baseline.status_code == 200, baseline.text
    baseline_total = baseline.json()["lots_total"]
    assert_public_visibility(True, baseline_total)
    maintenance = lot.transition("maintenance")
    assert maintenance.status_code == 200, maintenance.text
    assert maintenance.json() == lot.initial | {
        "status": "maintenance",
        "version": 2,
        "is_bookable": False,
    }
    assert_public_visibility(False, baseline_total - 1)

    records = asyncio.run(occupancies(lot))
    (maintenance_id,) = records.keys() - {past_id, released_id}
    opened = records[maintenance_id]
    assert opened.kind == "maintenance"
    assert opened.status == "active"
    assert opened.ref_id == lot.id
    assert opened.created_by == owner_id
    assert opened.period.lower is not None and opened.period.lower >= now
    assert opened.period.lower_inc and opened.period.upper_inf

    general_calendar = "/api/v1/admin/calendar"
    lot_calendar = f"{lot.url}/calendar"
    for endpoint in (general_calendar, lot_calendar):
        result = lot.client.get(endpoint, headers=lot.headers, params=params)
        assert result.status_code == 200, result.text
        (event,) = result.json()
        assert event["id"] == str(maintenance_id)
        assert event["kind"] == "maintenance"
        assert event["status"] == "active"
        assert datetime.fromisoformat(event["start_time"]) == window.start
        assert datetime.fromisoformat(event["end_time"]) == window.end

    async def active_period() -> TimeRange:
        async with db_session(lot.tenant_id) as session:
            (record,) = await OccupancyRepository(session).list_active(lot_id=lot.id, period=window)
            assert record.id == maintenance_id
            return record.period

    assert asyncio.run(active_period()) == window

    before_exit = datetime.now(UTC)
    exited = lot.transition(target)
    assert exited.status_code == 200, exited.text
    assert exited.json() == lot.initial | {
        "status": target,
        "version": 3,
        "is_bookable": target == "active",
    }
    upper_limit = datetime.now(UTC)
    assert_public_visibility(target == "active", baseline_total - (target == "archived"))
    assert lot.client.get(lot_calendar, headers=lot.headers, params=params).json() == []

    retained = asyncio.run(occupancies(lot))
    assert set(retained) == set(records)
    closed = retained[maintenance_id]
    assert closed.status == "released"
    assert closed.period.lower == opened.period.lower
    assert closed.period.upper is not None and before_exit <= closed.period.upper <= upper_limit
    assert not closed.period.upper_inc
    assert (retained[past_id].status, retained[past_id].period) == ("active", past)
    assert (retained[released_id].status, retained[released_id].period) == ("released", released)
    events = asyncio.run(status_audit(lot))
    assert all(event.actor_id == owner_id for event in events)
    assert [event.metadata_json for event in events] == [
        {"old_status": "active", "new_status": "maintenance"},
        {"old_status": "maintenance", "new_status": target},
    ]


def test_future_owner_block_conflicts_with_indefinite_maintenance(lot: OwnerLot) -> None:
    start = datetime.now(UTC) + timedelta(days=7)
    block = lot.client.post(
        f"{lot.url}/blocks",
        headers=lot.headers,
        json={
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(hours=2)).isoformat(),
            "reason": "Owner service appointment",
        },
    )
    assert block.status_code == 201, block.text
    assert_problem(lot.transition("maintenance"), 409, "slot_taken")
    assert lot.detail() == lot.initial
    records = asyncio.run(occupancies(lot))
    (only_block,) = records.values()
    assert str(only_block.id) == block.json()["id"]
    assert only_block.kind == "block" and only_block.status == "active"
    assert asyncio.run(status_audit(lot)) == []


def test_concurrent_maintenance_requests_apply_one_transition(lot: OwnerLot) -> None:
    start = Barrier(2, timeout=5)

    def transition() -> Response:
        start.wait()
        return lot.transition("maintenance")

    with ThreadPoolExecutor(max_workers=2) as requests:
        first = requests.submit(transition)
        second = requests.submit(transition)
        for response in (first.result(timeout=10), second.result(timeout=10)):
            assert response.status_code == 200, response.text
            assert response.json()["version"] == 2

    (only_maintenance,) = asyncio.run(occupancies(lot)).values()
    assert only_maintenance.kind == "maintenance"
    assert only_maintenance.period.upper_inf
    (entry,) = asyncio.run(status_audit(lot))
    assert entry.metadata_json == {"old_status": "active", "new_status": "maintenance"}


def test_booking_waits_for_archive_and_rechecks_status(
    lot: OwnerLot, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def race() -> Response:
        loop = asyncio.get_running_loop()
        audit_reached = asyncio.Event()
        release_audit = asyncio.Event()
        original_add = AuditRepository.add

        async def pause_archive_audit(repository: AuditRepository, entry: AuditEntry) -> None:
            if entry.action == STATUS_ACTION:
                loop.call_soon_threadsafe(audit_reached.set)
                gate = asyncio.run_coroutine_threadsafe(release_audit.wait(), loop)
                await asyncio.wrap_future(gate)
            await original_add(repository, entry)

        monkeypatch.setattr(AuditRepository, "add", pause_archive_audit)
        archive_task = asyncio.create_task(asyncio.to_thread(lot.transition, "archived"))
        try:
            await asyncio.wait_for(audit_reached.wait(), timeout=5)
            async with db_session(lot.tenant_id) as booking_session, db_session() as observer:
                booking_pid = await booking_session.scalar(select(func.pg_backend_pid()))
                now = datetime.now(UTC)
                service = OccupancyService(OccupancyRepository(booking_session))

                async def reserve_and_commit() -> None:
                    await service.reserve(
                        lot_id=lot.id,
                        kind="booking",
                        period=TimeRange(now, now + timedelta(hours=1)),
                    )
                    await booking_session.commit()

                booking_task = asyncio.create_task(reserve_and_commit())
                blocked = False
                try:
                    # Observe PostgreSQL waiting for the pending archive before letting it commit.
                    async with asyncio.timeout(5):
                        while not booking_task.done():
                            blocked = bool(
                                await observer.scalar(
                                    select(func.cardinality(func.pg_blocking_pids(booking_pid)))
                                )
                            )
                            if blocked:
                                break
                            await asyncio.sleep(0.02)
                finally:
                    release_audit.set()
                    (booking_outcome,) = await asyncio.gather(booking_task, return_exceptions=True)
                assert blocked, "booking did not wait for the archive transaction"
                assert isinstance(booking_outcome, LotUnavailableError), booking_outcome
        finally:
            release_audit.set()
            archive = await archive_task
        return archive

    archive = asyncio.run(race())
    assert archive.status_code == 200, archive.text
    assert lot.detail()["status"] == "archived"
    assert asyncio.run(occupancies(lot)) == {}
    (entry,) = asyncio.run(status_audit(lot))
    assert entry.metadata_json == {"old_status": "active", "new_status": "archived"}


def test_database_rejection_of_audit_rolls_back_maintenance(
    lot: OwnerLot, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_add = AuditRepository.add

    async def insert_invalid_action(repository: AuditRepository, entry: AuditEntry) -> None:
        await real_add(repository, replace(entry, action="invalid.action"))

    with monkeypatch.context() as fault:
        fault.setattr(AuditRepository, "add", insert_invalid_action)
        assert_problem(lot.transition("maintenance"), 500, "internal_error")

    assert lot.detail() == lot.initial
    assert asyncio.run(occupancies(lot)) == {}
    assert asyncio.run(status_audit(lot)) == []
    recovered = lot.transition("maintenance")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["version"] == 2
    assert len(asyncio.run(status_audit(lot))) == 1
