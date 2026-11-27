from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import Range

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.security.password_hasher import Argon2PasswordHasher
from tests.api.auth_helpers import enable_mfa, login_with_mfa

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
JWT_SECRET = "test-secret-keep-rollin-0123456789abcdef"
PASSWORD = "Bike-Rider-2026!"
NOW = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class SeededCalendarAPI:
    domain_a: str
    domain_b: str
    tenant_a: UUID
    tenant_b: UUID
    owner_a_id: UUID
    owner_a_email: str
    admin_a_id: UUID
    admin_a_email: str
    user_a_email: str
    owner_b_email: str
    category_a_id: UUID
    lot_a_id: UUID
    lot_b_id: UUID
    booking_ref_id: UUID
    active_block_id: UUID


def seed_calendar() -> SeededCalendarAPI:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    hasher = Argon2PasswordHasher()
    tenant_a = Tenant(
        id=uuid4(),
        name="Calendar API A",
        slug=f"calendar-api-a-{suffix}",
        domain=f"calendar-api-a-{suffix}.test",
        subdomain=f"calendar-api-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Calendar API B",
        slug=f"calendar-api-b-{suffix}",
        domain=f"calendar-api-b-{suffix}.test",
        subdomain=f"calendar-api-b-{suffix}",
    )
    password_hash = hasher.hash(PASSWORD)
    owner_a = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"owner-{suffix}@example.com",
        name="Owner",
        role="owner",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    admin_a = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"admin-{suffix}@example.com",
        name="Admin",
        role="admin",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    user_a = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"user-{suffix}@example.com",
        name="User",
        role="user",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    owner_b = User(
        id=uuid4(),
        tenant_id=tenant_b.id,
        email=f"owner-b-{suffix}@example.com",
        name="Owner B",
        role="owner",
        password_hash=password_hash,
        verification_status="approved",
        is_active=True,
        token_version=1,
    )
    enable_mfa(owner_a)
    enable_mfa(admin_a)
    enable_mfa(owner_b)
    category_a = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        name="Calendar API category",
        slug=f"calendar-api-cat-{suffix}",
        description=None,
        is_archived=False,
        version=1,
    )
    category_b = CategoryRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        name="Calendar API category B",
        slug=f"calendar-api-cat-b-{suffix}",
        description=None,
        is_archived=False,
        version=1,
    )
    lot_a = LotRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        category_id=category_a.id,
        slug=f"calendar-api-lot-{suffix}",
        name="Calendar API lot",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type=None,
        allowed_durations=[1],
        status="active",
        version=1,
    )
    lot_b = LotRecord(
        id=uuid4(),
        tenant_id=tenant_b.id,
        category_id=category_b.id,
        slug=f"calendar-api-lot-b-{suffix}",
        name="Calendar API lot B",
        description=None,
        photos=[],
        characteristics={},
        rental_unit="day",
        battery_type=None,
        allowed_durations=[1],
        status="active",
        version=1,
    )
    booking_ref_id = uuid4()
    booking = OccupancyRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        kind="booking",
        period=Range(NOW + timedelta(hours=1), NOW + timedelta(hours=2), bounds="[)"),
        ref_id=booking_ref_id,
        status="active",
    )
    active_block = OccupancyRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        kind="block",
        period=Range(NOW + timedelta(hours=5), NOW + timedelta(hours=6), bounds="[)"),
        ref_id=None,
        status="active",
        reason="Активный блок",
        created_by=owner_a.id,
    )
    released_block = OccupancyRecord(
        id=uuid4(),
        tenant_id=tenant_a.id,
        lot_id=lot_a.id,
        kind="block",
        period=Range(NOW + timedelta(hours=7), NOW + timedelta(hours=8), bounds="[)"),
        ref_id=None,
        status="released",
        reason="Освобождённый блок",
        created_by=owner_a.id,
    )

    async def seed() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                session.add_all([tenant_a, tenant_b])
                await session.flush()
                session.add_all([owner_a, admin_a, user_a, owner_b])
                session.add_all([category_a, category_b])
                session.add_all([lot_a, lot_b])
                session.add_all([booking, active_block, released_block])
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    return SeededCalendarAPI(
        domain_a=tenant_a.domain,
        domain_b=tenant_b.domain,
        tenant_a=tenant_a.id,
        tenant_b=tenant_b.id,
        owner_a_id=owner_a.id,
        owner_a_email=owner_a.email,
        admin_a_id=admin_a.id,
        admin_a_email=admin_a.email,
        user_a_email=user_a.email,
        owner_b_email=owner_b.email,
        category_a_id=category_a.id,
        lot_a_id=lot_a.id,
        lot_b_id=lot_b.id,
        booking_ref_id=booking_ref_id,
        active_block_id=active_block.id,
    )


def cleanup_calendar(tenant_ids: tuple[UUID, UUID]) -> None:
    assert DATABASE_URL is not None

    async def cleanup() -> None:
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(
                    delete(AuditLogRecord).where(AuditLogRecord.tenant_id.in_(tenant_ids))
                )
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(cleanup())


@pytest.fixture
def seeded() -> Iterator[SeededCalendarAPI]:
    value = seed_calendar()
    try:
        yield value
    finally:
        cleanup_calendar((value.tenant_a, value.tenant_b))


def client_for(
    domain: str, *, browser_headers: bool = True, client_host: str = "testclient"
) -> TestClient:
    assert DATABASE_URL is not None
    settings = Settings(
        database_url=DATABASE_URL,
        app_env="test",
        platform_domain="platform.test",
        allow_tenant_header=True,
        database_role="keep_rollin_app",
        jwt_secret=JWT_SECRET,
        refresh_cookie_secure=True,
    )
    headers = (
        {
            "Sec-Fetch-Site": "same-origin",
            "Origin": f"https://{domain}",
        }
        if browser_headers
        else None
    )
    return TestClient(
        create_app(settings),
        base_url=f"https://{domain}",
        headers=headers,
        client=(client_host, 50000),
    )


def login(client: TestClient, email: str) -> str:
    payload = login_with_mfa(client, email)
    return str(payload["access_token"])


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def period_query(hours_before: int = 0, hours_after: int = 6) -> dict[str, str]:
    return {
        "from": (NOW - timedelta(hours=hours_before)).isoformat(),
        "to": (NOW + timedelta(hours=hours_after)).isoformat(),
    }


def test_calendar_permissions_filters_and_no_store(seeded: SeededCalendarAPI) -> None:
    with client_for(seeded.domain_a) as client:
        owner_token = login(client, seeded.owner_a_email)
        admin_token = login(client, seeded.admin_a_email)
        user_token = login(client, seeded.user_a_email)
        owner_headers = auth(owner_token)

        calendar = client.get(
            "/api/v1/admin/calendar",
            headers=owner_headers,
            params=period_query(),
        )
        assert calendar.status_code == 200
        assert calendar.headers["Cache-Control"] == "no-store"
        events = calendar.json()
        assert len(events) == 2
        booking_event = next(item for item in events if item["kind"] == "booking")
        assert booking_event["rental_id"] == str(seeded.booking_ref_id)
        assert booking_event["block_id"] is None
        assert booking_event["status"] == "booked"

        admin_calendar = client.get(
            "/api/v1/admin/calendar",
            headers=auth(admin_token),
            params=period_query(),
        )
        assert admin_calendar.status_code == 200
        assert (
            client.get(
                "/api/v1/admin/calendar",
                headers=auth(user_token),
                params=period_query(),
            ).status_code
            == 403
        )
        assert client.get("/api/v1/admin/calendar", params=period_query()).status_code == 401

        by_lot = client.get(
            "/api/v1/admin/calendar",
            headers=owner_headers,
            params={**period_query(), "lot_id": str(seeded.lot_a_id)},
        )
        assert by_lot.status_code == 200
        assert len(by_lot.json()) == 2

        by_category = client.get(
            "/api/v1/admin/calendar",
            headers=owner_headers,
            params={**period_query(), "category_id": str(seeded.category_a_id)},
        )
        assert by_category.status_code == 200
        assert len(by_category.json()) == 2

        booked_only = client.get(
            "/api/v1/admin/calendar",
            headers=owner_headers,
            params={**period_query(), "status": "booked"},
        )
        assert booked_only.status_code == 200
        assert len(booked_only.json()) == 1
        assert booked_only.json()[0]["kind"] == "booking"

        active_only = client.get(
            "/api/v1/admin/calendar",
            headers=owner_headers,
            params={**period_query(), "status": "active"},
        )
        assert active_only.status_code == 200
        assert len(active_only.json()) == 1
        assert active_only.json()[0]["kind"] == "block"

        released_only = client.get(
            "/api/v1/admin/calendar",
            headers=owner_headers,
            params={**period_query(hours_after=9), "status": "released"},
        )
        assert released_only.status_code == 200
        assert len(released_only.json()) == 1
        assert released_only.json()[0]["status"] == "released"

        lot_calendar = client.get(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/calendar",
            headers=owner_headers,
            params=period_query(),
        )
        assert lot_calendar.status_code == 200
        assert lot_calendar.headers["Cache-Control"] == "no-store"
        foreign_lot = client.get(
            f"/api/v1/admin/lots/{seeded.lot_b_id}/calendar",
            headers=owner_headers,
            params=period_query(),
        )
        assert foreign_lot.status_code == 404

        too_long = client.get(
            "/api/v1/admin/calendar",
            headers=owner_headers,
            params={
                "from": NOW.isoformat(),
                "to": (NOW + timedelta(days=91)).isoformat(),
            },
        )
        assert too_long.status_code == 422


def test_block_create_conflict_delete_and_validation(seeded: SeededCalendarAPI) -> None:
    with client_for(seeded.domain_a) as client:
        owner_token = login(client, seeded.owner_a_email)
        headers = auth(owner_token)
        free_start = datetime(2026, 12, 10, 12, tzinfo=UTC)
        free_end = datetime(2026, 12, 10, 13, tzinfo=UTC)

        created = client.post(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks",
            headers=headers,
            json={
                "start_time": free_start.isoformat(),
                "end_time": free_end.isoformat(),
                "reason": "Плановое обслуживание",
            },
        )
        assert created.status_code == 201
        assert created.headers["Cache-Control"] == "no-store"
        block = created.json()
        assert block["reason"] == "Плановое обслуживание"
        assert block["created_by"] == str(seeded.owner_a_id)
        assert block["lot_id"] == str(seeded.lot_a_id)

        calendar = client.get(
            "/api/v1/admin/calendar",
            headers=headers,
            params={
                "from": (free_start - timedelta(days=1)).isoformat(),
                "to": (free_end + timedelta(days=1)).isoformat(),
            },
        )
        block_event = next(item for item in calendar.json() if item.get("block_id") == block["id"])
        assert block_event["reason"] == "Плановое обслуживание"

        overlap_block = client.post(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks",
            headers=headers,
            json={
                "start_time": free_start.isoformat(),
                "end_time": free_end.isoformat(),
                "reason": "Повтор",
            },
        )
        assert overlap_block.status_code == 409
        assert overlap_block.json()["code"] == "slot_taken"

        overlap_booking = client.post(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks",
            headers=headers,
            json={
                "start_time": NOW.isoformat(),
                "end_time": (NOW + timedelta(hours=1)).isoformat(),
                "reason": "Пересечение",
            },
        )
        assert overlap_booking.status_code == 409

        short_reason = client.post(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks",
            headers=headers,
            json={
                "start_time": (NOW + timedelta(hours=5)).isoformat(),
                "end_time": (NOW + timedelta(hours=6)).isoformat(),
                "reason": "ab",
            },
        )
        assert short_reason.status_code == 422

        bad_period = client.post(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks",
            headers=headers,
            json={
                "start_time": (NOW + timedelta(hours=6)).isoformat(),
                "end_time": (NOW + timedelta(hours=5)).isoformat(),
                "reason": "Период",
            },
        )
        assert bad_period.status_code == 422

        deleted = client.delete(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks/{block['id']}",
            headers=headers,
        )
        assert deleted.status_code == 204
        repeat_delete = client.delete(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks/{block['id']}",
            headers=headers,
        )
        assert repeat_delete.status_code == 204
        missing_delete = client.delete(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks/{uuid4()}",
            headers=headers,
        )
        assert missing_delete.status_code == 404

        recreated = client.post(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks",
            headers=headers,
            json={
                "start_time": free_start.isoformat(),
                "end_time": free_end.isoformat(),
                "reason": "После удаления",
            },
        )
        assert recreated.status_code == 201

        aligned = client.post(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks",
            headers=headers,
            json={
                "start_time": "2026-12-14T21:00:00Z",
                "end_time": "2026-12-15T21:00:00Z",
                "reason": "Целые сутки",
            },
        )
        assert aligned.status_code == 201
        assert aligned.json()["start_time"].startswith("2026-12-14T21:00:00")
        assert aligned.json()["end_time"].startswith("2026-12-15T21:00:00")


def test_calendar_tenant_isolation_and_csrf(seeded: SeededCalendarAPI) -> None:
    with client_for(seeded.domain_b) as client_b:
        owner_b_token = login(client_b, seeded.owner_b_email)
        events = client_b.get(
            "/api/v1/admin/calendar",
            headers=auth(owner_b_token),
            params=period_query(),
        )
        assert events.status_code == 200
        assert events.json() == []
        foreign_block = client_b.post(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks",
            headers=auth(owner_b_token),
            json={
                "start_time": (NOW + timedelta(hours=7)).isoformat(),
                "end_time": (NOW + timedelta(hours=8)).isoformat(),
                "reason": "Чужой лот",
            },
        )
        assert foreign_block.status_code == 404
        foreign_calendar = client_b.get(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/calendar",
            headers=auth(owner_b_token),
            params=period_query(),
        )
        assert foreign_calendar.status_code == 404
        foreign_delete = client_b.delete(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks/{seeded.active_block_id}",
            headers=auth(owner_b_token),
        )
        assert foreign_delete.status_code == 404

    with client_for(seeded.domain_a) as client:
        owner_token = login(client, seeded.owner_a_email)
        user_token = login(client, seeded.user_a_email)
        still_active = client.get(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/calendar",
            headers=auth(owner_token),
            params=period_query(),
        )
        assert still_active.status_code == 200
        assert any(item["block_id"] == str(seeded.active_block_id) for item in still_active.json())
        assert (
            client.post(
                f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks",
                headers=auth(user_token),
                json={
                    "start_time": (NOW + timedelta(hours=7)).isoformat(),
                    "end_time": (NOW + timedelta(hours=8)).isoformat(),
                    "reason": "User block",
                },
            ).status_code
            == 403
        )

    with client_for(seeded.domain_a, browser_headers=False) as bare:
        blocked = bare.post(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks",
            headers=auth(owner_token),
            json={
                "start_time": (NOW + timedelta(hours=7)).isoformat(),
                "end_time": (NOW + timedelta(hours=8)).isoformat(),
                "reason": "No CSRF",
            },
        )
        blocked_delete = bare.delete(
            f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks/{uuid4()}",
            headers=auth(owner_token),
        )
    assert blocked.status_code == 403
    assert blocked_delete.status_code == 403
