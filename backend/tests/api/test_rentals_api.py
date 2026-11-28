import asyncio
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import Response
from sqlalchemy import select, update

from app.db import configure_session, create_engine, create_session_factory
from app.models import User
from src.domain.entities.outbox_message import OutboxMessage
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.repositories.battery_stock_repository import BatteryStockRepository
from src.infrastructure.postgres.repositories.offer_repository import OfferRepository
from src.infrastructure.postgres.repositories.outbox_repository import OutboxRepository
from tests.api.test_admin_calendar_api import (
    DATABASE_URL,
    SeededCalendarAPI,
    auth,
    cleanup_calendar,
    client_for,
    login,
    seed_calendar,
)
from tests.api.test_admin_lots_api import LOTS, payload

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL integration tests")
RENTALS = "/api/v1/rentals"
ME = "/api/v1/me/rentals"
ADMIN = "/api/v1/admin/rentals"


@pytest.fixture
def seeded() -> Iterator[SeededCalendarAPI]:
    value = seed_calendar()
    try:
        yield value
    finally:
        cleanup_calendar((value.tenant_a, value.tenant_b))


def prepare(
    seeded: SeededCalendarAPI,
    *,
    accepted: bool = True,
    approved: bool = True,
    quantity: int | None = None,
) -> None:
    assert DATABASE_URL is not None

    async def write() -> None:
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine).begin() as session:
                configure_session(
                    session, tenant_id=seeded.tenant_a, database_role="keep_rollin_app"
                )
                user = await session.scalar(select(User).where(User.email == seeded.user_a_email))
                assert user is not None
                user.verification_status = "approved" if approved else "pending"
                offers = OfferRepository(session)
                offer = await offers.create_draft(title="Rental terms", body="Test terms")
                await offers.publish(offer.id)
                if accepted:
                    await offers.accept(user_id=user.id, offer_version_id=offer.id, ip=None)
                if quantity is not None:
                    await BatteryStockRepository(session).create("48v", "48 V", quantity)
        finally:
            await engine.dispose()

    asyncio.run(write())


def booking(lot: dict[str, object], start: datetime, *, count: int = 0) -> dict[str, str]:
    variants = lot["variants"]
    assert isinstance(variants, list)
    selected = next(item for item in variants if item["battery_count"] == count)
    return {
        "lot_id": str(lot["id"]),
        "variant_id": str(selected["id"]),
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(days=1)).isoformat(),
    }


def new_lot(seeded: SeededCalendarAPI, owner: dict[str, str]) -> dict[str, object]:
    with client_for(seeded.domain_a) as client:
        response = client.post(LOTS, headers=owner, json=payload(seeded.category_a_id))
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


def key(headers: dict[str, str]) -> dict[str, str]:
    return headers | {"Idempotency-Key": str(uuid4())}


def actors(seeded: SeededCalendarAPI) -> tuple[dict[str, str], dict[str, str]]:
    with client_for(seeded.domain_a) as client:
        return auth(login(client, seeded.user_a_email)), auth(login(client, seeded.owner_a_email))


def test_booking_guards_and_price_snapshot(seeded: SeededCalendarAPI) -> None:
    prepare(seeded, approved=False, accepted=False)
    customer, owner = actors(seeded)
    lot = new_lot(seeded, owner)
    start = datetime.now(UTC) + timedelta(days=3)
    body = booking(lot, start)
    variant_id = body["variant_id"]
    header = key(customer)
    quote_path = f"/api/v1/public/lots/{lot['slug']}/quote"
    quote_params = {
        "start": body["end_time"],
        "end": (start + timedelta(days=2)).isoformat(),
    }
    with client_for(seeded.domain_a) as client:
        assert client.post(RENTALS, headers=key({}), json=body).status_code == 401
        blocked = client.post(RENTALS, headers=header, json=body)
        assert blocked.status_code == 403 and blocked.json()["code"] == "verification_required"
        assert blocked.headers["Cache-Control"] == "no-store"
        prepare(seeded, accepted=False)
        blocked = client.post(RENTALS, headers=header, json=body)
        assert blocked.status_code == 403 and blocked.json()["code"] == "offer_not_accepted"
        prepare(seeded)
        assert client.post(RENTALS, headers=customer, json=body).status_code == 422
        csrf = client.post(RENTALS, headers=header | {"Sec-Fetch-Site": "cross-site"}, json=body)
        assert csrf.status_code == 403
        invalid = client.post(RENTALS, headers=header, json=body | {"variant_id": str(uuid4())})
        assert invalid.status_code == 422 and "variant_id" in invalid.json()["fields"]
        too_long = client.post(
            RENTALS,
            headers=header,
            json=body | {"end_time": (start + timedelta(days=31)).isoformat()},
        )
        assert (
            too_long.status_code == 422 and too_long.json()["code"] == "rental_period_not_allowed"
        )
        horizon = client.post(
            RENTALS, headers=header, json=booking(lot, start + timedelta(days=80))
        )
        assert horizon.status_code == 422
        short = client.post(
            RENTALS,
            headers=header,
            json=body | {"end_time": (start + timedelta(minutes=59)).isoformat()},
        )
        assert short.status_code == 422 and short.json()["code"] == "rental_period_not_allowed"

        created = client.post(RENTALS, headers=header, json=body | {"price_minor": 1})
        assert created.status_code == 201, created.text
        saved = created.json()
        assert saved["price_minor"] == 4900
        assert saved["status"] == "booked"
        assert created.headers["Cache-Control"] == "no-store"
        assert datetime.fromisoformat(saved["cancellation_deadline"]) == start - timedelta(days=1)
        echoed = client.post(RENTALS, headers=header, json=body)
        assert echoed.content == created.content
        assert echoed.headers["Idempotent-Replayed"] == "true"
        duplicate = client.post(RENTALS, headers=key(customer), json=body)
        assert duplicate.status_code == 409 and duplicate.json()["code"] == "slot_taken"
        assert duplicate.headers["Cache-Control"] == "no-store"
        conflict = client.post(
            RENTALS, headers=header, json=booking(lot, start + timedelta(days=2))
        )
        assert conflict.status_code == 422 and conflict.json()["code"] == "idempotency_conflict"
        assert conflict.headers["Cache-Control"] == "no-store"

        quote_before = client.get(quote_path, params=quote_params)
        assert quote_before.status_code == 200, quote_before.text
        before = next(
            item for item in quote_before.json()["variants"] if item["variant_id"] == variant_id
        )
        assert before["available"] and before["price_total_minor"] == saved["price_minor"]

        variants = payload(seeded.category_a_id)["variants"]
        assert isinstance(variants, list)
        changed = client.patch(
            f"{LOTS}/{lot['id']}",
            headers=owner,
            json={
                "version": lot["version"],
                "variants": [
                    variant
                    | {
                        "price_tiers": [{"min_units": 1, "price_per_unit_minor": 9900}],
                    }
                    if variant["battery_count"] == 0
                    else variant
                    for variant in variants
                ],
            },
        )
        assert changed.status_code == 200, changed.text
        updated = next(item for item in changed.json()["variants"] if item["battery_count"] == 0)
        assert updated["id"] == variant_id

        quote_after = client.get(quote_path, params=quote_params)
        assert quote_after.status_code == 200, quote_after.text
        after = next(
            item for item in quote_after.json()["variants"] if item["variant_id"] == variant_id
        )
        assert after["available"] and after["price_total_minor"] == 9900

        detail = client.get(f"{ME}/{saved['id']}", headers=customer)
        assert detail.status_code == 200 and detail.json()["price_minor"] == 4900
        assert client.get(f"{ME}/{saved['id']}", headers=owner).status_code == 404


@pytest.mark.parametrize(
    "share_lot, conflict", [(True, "slot_taken"), (False, "battery_unavailable")]
)
def test_simultaneous_booking_respects_slot_and_stock(
    seeded: SeededCalendarAPI, share_lot: bool, conflict: str
) -> None:
    prepare(seeded, quantity=1)
    customer, owner = actors(seeded)
    first = new_lot(seeded, owner)
    second = first if share_lot else new_lot(seeded, owner)
    start = datetime.now(UTC) + timedelta(days=2)
    barrier = Barrier(2, timeout=10)

    def reserve(lot: dict[str, object]) -> Response:
        with client_for(seeded.domain_a) as client:
            barrier.wait()
            return cast(
                Response,
                client.post(RENTALS, headers=key(customer), json=booking(lot, start, count=1)),
            )

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(reserve, (first, second)))
    assert sorted(item.status_code for item in results) == [201, 409], [x.text for x in results]
    assert next(item for item in results if item.status_code == 409).json()["code"] == conflict
    with client_for(seeded.domain_a) as client:
        adjacent = client.post(
            RENTALS,
            headers=key(customer),
            json=booking(second, start + timedelta(days=1), count=1),
        )
        assert adjacent.status_code == 201, adjacent.text


def test_cancellation_and_closure_release_only_on_success(
    seeded: SeededCalendarAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare(seeded)
    customer, owner = actors(seeded)
    lot = new_lot(seeded, owner)
    start = datetime.now(UTC) + timedelta(hours=4)
    with client_for(seeded.domain_a) as client:
        late = client.post(RENTALS, headers=key(customer), json=booking(lot, start))
        assert late.status_code == 201, late.text
        rental_id = late.json()["id"]
        my_cancel = f"{ME}/{rental_id}/cancel"
        staff_cancel = f"{ADMIN}/{rental_id}/cancel"
        after_deadline = client.post(my_cancel, headers=customer)
        assert after_deadline.status_code == 409
        assert after_deadline.json()["code"] == "cancellation_not_allowed"
        assert client.post(my_cancel, headers=owner).status_code == 404
        assert client.post(staff_cancel, headers=owner, json={"reason": " "}).status_code == 422

        async def fail(self: OutboxRepository, message: OutboxMessage) -> None:
            raise RuntimeError("Injected outbox failure")

        with monkeypatch.context() as patch:
            patch.setattr(OutboxRepository, "add", fail)
            failed = client.post(staff_cancel, headers=owner, json={"reason": "Test failure"})
            assert failed.status_code == 500
        assert client.get(f"{ME}/{rental_id}", headers=customer).json()["status"] == "booked"
        booked = client.post(RENTALS, headers=key(customer), json=booking(lot, start))
        assert booked.status_code == 409 and booked.json()["code"] == "slot_taken"

        cancelled = client.post(staff_cancel, headers=owner, json={"reason": "Initial reason"})
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        repeat = client.post(staff_cancel, headers=owner, json={"reason": "Change reason"})
        assert repeat.status_code == 200 and repeat.json()["version"] == cancelled.json()["version"]
        booked = client.post(RENTALS, headers=key(customer), json=booking(lot, start))
        assert booked.status_code == 201, booked.text
        new_id = booked.json()["id"]
        adjacent = client.post(
            RENTALS, headers=key(customer), json=booking(lot, start + timedelta(days=1))
        )
        assert adjacent.status_code == 201, adjacent.text
        close = f"{ADMIN}/{new_id}/close"
        maintain = {"comment": "Returned", "lot_status": "maintenance"}
        blocked = client.post(close, headers=owner, json=maintain)
        assert blocked.status_code == 409 and blocked.json()["code"] == "slot_taken"
        assert client.get(f"{ME}/{new_id}", headers=customer).json()["status"] == "booked"
        cancelled_adjacent = client.post(f"{ME}/{adjacent.json()['id']}/cancel", headers=customer)
        assert cancelled_adjacent.status_code == 200
        assert (
            client.post(f"{ME}/{adjacent.json()['id']}/cancel", headers=customer).status_code == 200
        )
        successful = client.post(close, headers=owner, json=maintain)
        assert successful.status_code == 200 and successful.json()["status"] == "completed"
        detail = client.get(f"{ADMIN}/{new_id}", headers=owner).json()
        assert detail["completed_at"] and detail["closed_by"]
        terminal = client.post(close, headers=owner, json=maintain)
        assert terminal.status_code == 409 and terminal.json()["code"] == "rental_already_closed"
        assert client.get(f"{LOTS}/{lot['id']}", headers=owner).json()["status"] == "maintenance"

    async def rows() -> None:
        assert DATABASE_URL is not None
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine)() as session:
                cancelled_record = await session.get(RentalRecord, UUID(rental_id))
                closed_record = await session.get(RentalRecord, UUID(new_id))
                assert cancelled_record and closed_record
                assert cancelled_record.cancellation_reason == "Initial reason"
                occupancy = await session.get(OccupancyRecord, closed_record.occupancy_id)
                assert occupancy and occupancy.status == "released"
                events = list(
                    await session.scalars(
                        select(OutboxMessageRecord.event_type).where(
                            OutboxMessageRecord.tenant_id == seeded.tenant_a
                        )
                    )
                )
                assert events.count("booking.confirmed") == 3
                assert events.count("booking.cancelled") == 2
                assert events.count("rental.closed") == 1
                audit = list(
                    await session.scalars(
                        select(AuditLogRecord).where(AuditLogRecord.tenant_id == seeded.tenant_a)
                    )
                )
                bookings = [entry for entry in audit if entry.action == "rental.booked"]
                assert len(bookings) == 3 and all(entry.actor_role == "user" for entry in bookings)
                assert sum(entry.action == "rental.cancelled" for entry in audit) == 2
                closed = [entry for entry in audit if entry.action == "rental.closed"]
                assert len(closed) == 1 and closed[0].metadata_json == {"lot_status": "maintenance"}
        finally:
            await engine.dispose()

    asyncio.run(rows())


def test_overdue_close_can_reactivate_lot(seeded: SeededCalendarAPI) -> None:
    prepare(seeded)
    customer, owner = actors(seeded)
    lot = new_lot(seeded, owner)
    start = datetime.now(UTC) + timedelta(days=3)
    with client_for(seeded.domain_a) as client:
        response = client.post(RENTALS, headers=key(customer), json=booking(lot, start))
        assert response.status_code == 201, response.text
        identifier = UUID(response.json()["id"])
        next_start = start + timedelta(days=2)
        future = client.post(RENTALS, headers=key(customer), json=booking(lot, next_start))
        assert future.status_code == 201, future.text
        future_id = future.json()["id"]

        async def put_overdue(rental_id: UUID) -> None:
            from src.infrastructure.postgres.models.lot_record import LotRecord

            assert DATABASE_URL is not None
            engine = create_engine(DATABASE_URL)
            try:
                async with create_session_factory(engine).begin() as session:
                    await session.execute(
                        update(RentalRecord)
                        .where(RentalRecord.id == rental_id)
                        .values(status="overdue")
                    )
                    await session.execute(
                        update(LotRecord)
                        .where(LotRecord.id == UUID(str(lot["id"])))
                        .values(status="overdue")
                    )
            finally:
                await engine.dispose()

        asyncio.run(put_overdue(identifier))
        forbidden_close = client.post(
            f"{ADMIN}/{future_id}/close",
            headers=owner,
            json={"comment": "Pending return", "lot_status": "active"},
        )
        assert forbidden_close.status_code == 409
        assert forbidden_close.json()["code"] == "lot_has_active_rental"
        assert client.get(f"{LOTS}/{lot['id']}", headers=owner).json()["status"] == "overdue"
        assert client.get(f"{ME}/{future_id}", headers=customer).json()["status"] == "booked"
        unreachable = client.post(
            RENTALS, headers=key(customer), json=booking(lot, start + timedelta(days=1))
        )
        assert unreachable.status_code == 409 and unreachable.json()["code"] == "lot_unavailable"

        asyncio.run(put_overdue(UUID(future_id)))
        response = client.post(
            f"{ADMIN}/{identifier}/close",
            headers=owner,
            json={"comment": "Returned", "lot_status": "active"},
        )
        assert response.status_code == 200 and response.json()["status"] == "completed"
        assert client.get(f"{LOTS}/{lot['id']}", headers=owner).json()["status"] == "overdue"
        response = client.post(
            f"{ADMIN}/{future_id}/close",
            headers=owner,
            json={"comment": "Returned last rental", "lot_status": "active"},
        )
        assert response.status_code == 200 and response.json()["status"] == "completed"
        assert client.get(f"{LOTS}/{lot['id']}", headers=owner).json()["status"] == "active"
        assert (
            client.post(RENTALS, headers=key(customer), json=booking(lot, start)).status_code == 201
        )
