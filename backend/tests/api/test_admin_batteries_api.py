import asyncio
from collections.abc import Iterator
from datetime import timedelta
from urllib.parse import quote
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db import create_engine, create_session_factory
from app.main import create_app
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from tests.api.test_admin_calendar_api import (
    DATABASE_URL,
    NOW,
    SeededCalendarAPI,
    auth,
    cleanup_calendar,
    client_for,
    login,
    seed_calendar,
)

BATTERIES = "/api/v1/admin/batteries"
STOCK = {"battery_type": "48v", "name": "48V", "quantity": 3}


@pytest.fixture
def seeded() -> Iterator[SeededCalendarAPI]:
    if not DATABASE_URL:
        pytest.skip("PostgreSQL DATABASE_URL is required")
    value = seed_calendar()
    try:
        yield value
    finally:
        cleanup_calendar((value.tenant_a, value.tenant_b))


def _add_booked_rental(seeded: SeededCalendarAPI) -> None:
    assert DATABASE_URL is not None

    async def insert() -> None:
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine)() as session:
                occupancy_id = await session.scalar(
                    select(OccupancyRecord.id).where(
                        OccupancyRecord.tenant_id == seeded.tenant_a,
                        OccupancyRecord.ref_id == seeded.booking_ref_id,
                    )
                )
                assert occupancy_id is not None
                session.add(
                    RentalRecord(
                        id=seeded.booking_ref_id,
                        tenant_id=seeded.tenant_a,
                        user_id=seeded.owner_a_id,
                        lot_id=seeded.lot_a_id,
                        occupancy_id=occupancy_id,
                        variant_id=uuid4(),
                        battery_type="48v",
                        battery_count=2,
                        start_time=NOW + timedelta(hours=1),
                        end_time=NOW + timedelta(hours=2),
                        cancellation_deadline=NOW,
                        price_minor=50000,
                        currency="RUB",
                        status="booked",
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(insert())


def test_owner_stock_crud_and_audit_are_tenant_scoped(seeded: SeededCalendarAPI) -> None:
    path = f"{BATTERIES}/48v"
    with client_for(seeded.domain_a) as client:
        anonymous = client.get(BATTERIES)
        assert anonymous.status_code == 401
        assert anonymous.headers["Cache-Control"] == "no-store"
        admin = auth(login(client, seeded.admin_a_email))
        assert client.get(BATTERIES, headers=admin).status_code == 403
        assert client.post(BATTERIES, headers=admin, json=STOCK).status_code == 403
        owner = auth(login(client, seeded.owner_a_email))

        created = client.post(BATTERIES, headers=owner, json=STOCK)
        assert created.status_code == 201, created.text
        assert created.headers["Cache-Control"] == "no-store"
        assert created.json() == {**STOCK, "peak_committed": 0}
        assert client.post(BATTERIES, headers=owner, json=STOCK).status_code == 409

        updated = client.patch(path, headers=owner, json={"quantity": 2})
        assert updated.status_code == 200, updated.text
        assert updated.headers["Cache-Control"] == "no-store"
        assert updated.json() == {**STOCK, "quantity": 2, "peak_committed": 0}
        listed = client.get(BATTERIES, headers=owner)
        assert listed.headers["Cache-Control"] == "no-store"
        assert listed.json() == [updated.json()]

        with client_for(seeded.domain_b) as other_client:
            other_owner = auth(login(other_client, seeded.owner_b_email))
            assert other_client.get(BATTERIES, headers=other_owner).json() == []
            assert (
                other_client.patch(path, headers=other_owner, json={"quantity": 1}).status_code
                == 404
            )
            assert other_client.delete(path, headers=other_owner).status_code == 404
            foreign_stock = other_client.post(BATTERIES, headers=other_owner, json=STOCK)
            assert foreign_stock.status_code == 201, foreign_stock.text

        deleted = client.delete(path, headers=owner)
        assert deleted.status_code == 204, deleted.text
        assert deleted.content == b""
        assert deleted.headers["Cache-Control"] == "no-store"
        assert client.delete(path, headers=owner).status_code == 404
        assert client.get(BATTERIES, headers=owner).json() == []
        log = client.get("/api/v1/admin/audit-log", headers=owner)
        assert log.status_code == 200, log.text

    entries = [entry for entry in log.json()["items"] if entry["entity_type"] == "battery_stock"]
    assert len(entries) == 3
    assert {entry["action"] for entry in entries} == {
        "battery_stock.created",
        "battery_stock.updated",
        "battery_stock.deleted",
    }
    assert {entry["actor_id"] for entry in entries} == {str(seeded.owner_a_id)}
    assert len({entry["entity_id"] for entry in entries}) == 1


def test_stock_cannot_drop_below_peak_or_be_deleted_in_use(seeded: SeededCalendarAPI) -> None:
    path = f"{BATTERIES}/48v"
    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        created = client.post(BATTERIES, headers=owner, json=STOCK)
        assert created.status_code == 201, created.text
        _add_booked_rental(seeded)

        response = client.patch(path, headers=owner, json={"quantity": 1})
        assert response.status_code == 409, response.text
        assert response.headers["Content-Type"] == "application/problem+json"
        problem = response.json()
        assert problem["code"] == "stock_below_committed"
        assert problem["fields"]["requested_quantity"] == "1"
        assert problem["fields"]["peak_committed"] == "2"
        assert "2" in problem["fields"]["quantity"]
        assert "1" in problem["detail"] and "2" in problem["detail"]
        assert client.get(BATTERIES, headers=owner).json() == [{**STOCK, "peak_committed": 2}]

        updated = client.patch(path, headers=owner, json={"quantity": 2})
        assert updated.status_code == 200, updated.text
        assert updated.json() == {**STOCK, "quantity": 2, "peak_committed": 2}
        assert client.delete(path, headers=owner).status_code == 409


def test_stock_writes_require_csrf_and_validate_quantity(seeded: SeededCalendarAPI) -> None:
    path = f"{BATTERIES}/48v"
    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        assert client.post(BATTERIES, headers=owner, json=STOCK).status_code == 201
        for quantity in (True, -1, 1.5, "1", 2**63):
            invalid = client.patch(path, headers=owner, json={"quantity": quantity})
            assert invalid.status_code == 422, invalid.text
            assert "quantity" in invalid.json()["fields"]
        for battery_type in (" ", ".", "..", "48\x00v", "🛵" * 257):
            invalid = client.post(
                BATTERIES, headers=owner, json={**STOCK, "battery_type": battery_type}
            )
            assert invalid.status_code == 422, invalid.text
            assert "battery_type" in invalid.json()["fields"]

    with client_for(seeded.domain_a, browser_headers=False) as client:
        assert client.get(BATTERIES, headers=owner).status_code == 200
        assert client.post(BATTERIES, headers=owner, json=STOCK).status_code == 403
        assert client.patch(path, headers=owner, json={"quantity": 1}).status_code == 403
        assert client.delete(path, headers=owner).status_code == 403


def test_stock_type_with_slash_remains_addressable(seeded: SeededCalendarAPI) -> None:
    stock = {**STOCK, "battery_type": "48V/720"}
    path = f"{BATTERIES}/{quote('48V/720', safe='')}"
    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        created = client.post(BATTERIES, headers=owner, json=stock)
        assert created.status_code == 201, created.text
        listed = client.get(BATTERIES, headers=owner)
        assert listed.status_code == 200, listed.text
        assert listed.json() == [{**stock, "peak_committed": 0}]
        updated = client.patch(path, headers=owner, json={"quantity": 2})
        assert updated.status_code == 200, updated.text
        assert updated.json() == {**stock, "quantity": 2, "peak_committed": 0}
        deleted = client.delete(path, headers=owner)
        assert deleted.status_code == 204, deleted.text
        assert client.get(BATTERIES, headers=owner).json() == []


def test_stock_openapi_keeps_frontend_schema_and_operation_ids() -> None:
    schema = create_app().openapi()
    listing = schema["paths"][BATTERIES]["get"]
    update = schema["paths"][f"{BATTERIES}/{{battery_type}}"]["patch"]
    assert listing["operationId"] == "listBatteryStock"
    assert update["operationId"] == "updateBatteryStock"
    assert listing["responses"]["200"]["content"]["application/json"]["schema"]["items"] == {
        "$ref": "#/components/schemas/BatteryStock"
    }
    assert update["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BatteryStock"
    }
    assert "BatteryStock" in schema["components"]["schemas"]
