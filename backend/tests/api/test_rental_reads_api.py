from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from src.domain.entities.user_account import UserRole
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord, RentalStatus
from src.infrastructure.security.token_service import JwtTokenService
from tests.api.auth_helpers import JWT_SECRET, enable_mfa

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")
ME = "/api/v1/me/rentals"
ADMIN = "/api/v1/admin/rentals"


@dataclass(frozen=True)
class SeededRentals:
    tenant: Tenant
    renter: User
    other_renter: User
    admin: User
    owner: User
    another_tenant: Tenant
    booked: RentalRecord
    active: RentalRecord
    overdue: RentalRecord
    completed: RentalRecord
    foreign: RentalRecord


async def _create_lot(session: AsyncSession, tenant: Tenant) -> LotVariantRecord:
    category = CategoryRecord(id=uuid4(), tenant_id=tenant.id, name="Bikes", slug="bikes")
    session.add(category)
    await session.flush()
    lot = LotRecord(
        id=uuid4(),
        tenant_id=tenant.id,
        category_id=category.id,
        name="Rental test lot",
        slug="rental-test-lot",
        photos=["https://static.example.test/lot.jpg"],
        rental_unit="hour",
        allowed_durations=[1],
        status="active",
    )
    session.add(lot)
    await session.flush()
    variant = LotVariantRecord(id=uuid4(), tenant_id=tenant.id, lot_id=lot.id, battery_count=0)
    session.add(variant)
    await session.flush()
    return variant


async def _create_rental(
    session: AsyncSession,
    *,
    renter: User,
    variant: LotVariantRecord,
    start: datetime,
    status: RentalStatus,
    closed_by: UUID | None = None,
) -> RentalRecord:
    rental_id, occupancy_id = uuid4(), uuid4()
    end = start + timedelta(hours=2)
    session.add(
        OccupancyRecord(
            id=occupancy_id,
            tenant_id=renter.tenant_id,
            lot_id=variant.lot_id,
            kind="booking",
            period=Range(start, end, bounds="[)"),
            ref_id=rental_id,
            status="released" if status == "completed" else "active",
        )
    )
    await session.flush()
    rental = RentalRecord(
        id=rental_id,
        tenant_id=renter.tenant_id,
        user_id=renter.id,
        lot_id=variant.lot_id,
        variant_id=variant.id,
        occupancy_id=occupancy_id,
        battery_count=0,
        start_time=start,
        end_time=end,
        status=status,
        price_minor=120000,
        currency="RUB",
        cancellation_deadline=start - timedelta(hours=1),
        completed_at=end if closed_by else None,
        closed_by=closed_by,
    )
    session.add(rental)
    await session.flush()
    return rental


@pytest.fixture(scope="module")
def seeded() -> Iterator[SeededRentals]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    factory = create_session_factory(engine)
    suffix = uuid4().hex[:8]
    primary = Tenant(
        id=uuid4(),
        name="Rental reads",
        slug=f"rental-reads-{suffix}",
        domain=f"rental-reads-{suffix}.test",
    )
    secondary = Tenant(
        id=uuid4(),
        name="Other tenant",
        slug=f"rental-reads-other-{suffix}",
        domain=f"rental-reads-other-{suffix}.test",
    )

    def actor(tenant: Tenant, role: UserRole, name: str) -> User:
        user = User(
            id=uuid4(),
            tenant_id=tenant.id,
            email=f"{name}-{suffix}@test.example",
            name=name,
            role=role,
        )
        if role != "user":
            enable_mfa(user)
        return user

    renter = actor(primary, "user", "renter")
    other_renter = actor(primary, "user", "other-renter")
    foreign_renter = actor(secondary, "user", "foreign-renter")
    admin = actor(primary, "admin", "admin")
    owner = actor(primary, "owner", "owner")

    async def seed() -> SeededRentals:
        try:
            async with factory() as session:
                session.add_all([primary, secondary])
                await session.flush()
                session.add_all([renter, other_renter, foreign_renter, admin, owner])
                await session.flush()
                variant = await _create_lot(session, primary)
                foreign_variant = await _create_lot(session, secondary)
                now = datetime.now(UTC)
                completed = await _create_rental(
                    session,
                    renter=other_renter,
                    variant=variant,
                    start=now - timedelta(hours=6),
                    status="completed",
                    closed_by=admin.id,
                )
                overdue = await _create_rental(
                    session,
                    renter=renter,
                    variant=variant,
                    start=now - timedelta(hours=4),
                    status="overdue",
                )
                active = await _create_rental(
                    session,
                    renter=renter,
                    variant=variant,
                    start=now - timedelta(hours=1),
                    status="active",
                )
                booked = await _create_rental(
                    session,
                    renter=renter,
                    variant=variant,
                    start=now + timedelta(hours=1),
                    status="booked",
                )
                foreign = await _create_rental(
                    session,
                    renter=foreign_renter,
                    variant=foreign_variant,
                    start=now + timedelta(hours=1),
                    status="booked",
                )
                await session.commit()
            return SeededRentals(
                primary,
                renter,
                other_renter,
                admin,
                owner,
                secondary,
                booked,
                active,
                overdue,
                completed,
                foreign,
            )
        finally:
            await engine.dispose()

    async def cleanup() -> None:
        try:
            async with factory() as session:
                await session.execute(
                    delete(Tenant).where(Tenant.id.in_((primary.id, secondary.id)))
                )
                await session.commit()
        finally:
            await engine.dispose()

    data = asyncio.run(seed())
    try:
        yield data
    finally:
        asyncio.run(cleanup())


def _client(tenant: Tenant) -> TestClient:
    settings = Settings(
        database_url=DATABASE_URL,
        app_env="test",
        platform_domain="platform.test",
        database_role="keep_rollin_app",
        jwt_secret=JWT_SECRET,
    )
    return TestClient(create_app(settings), base_url=f"https://{tenant.domain}")


def _auth(user: User) -> dict[str, str]:
    token = JwtTokenService(secret=JWT_SECRET).create_access(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=cast(UserRole, user.role),
        token_version=user.token_version,
    )
    return {"Authorization": f"Bearer {token}"}


def test_personal_reads_paginate_and_only_return_own_rentals(seeded: SeededRentals) -> None:
    with _client(seeded.tenant) as client:
        assert client.get(ME).status_code == 401
        headers = _auth(seeded.renter)
        ids = set()
        for offset in range(3):
            response = client.get(ME, params={"limit": 1, "offset": offset}, headers=headers)
            assert response.status_code == 200, response.text
            assert response.headers["Cache-Control"] == "no-store"
            page = response.json()
            assert (page["total"], page["limit"], page["offset"]) == (3, 1, offset)
            assert len(page["items"]) == 1
            assert "user" not in page["items"][0]
            ids.add(page["items"][0]["id"])
        assert ids == {str(item.id) for item in (seeded.booked, seeded.active, seeded.overdue)}

        filtered = client.get(ME, params={"status": "active"}, headers=headers)
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["remaining_seconds"] > 0
        assert client.get(ME, params={"limit": 101}, headers=headers).status_code == 422

        detail = client.get(f"{ME}/{seeded.overdue.id}", headers=headers)
        assert detail.status_code == 200, detail.text
        result = detail.json()
        assert result["status"] == "overdue"
        seconds = (seeded.overdue.end_time - datetime.now(UTC)).total_seconds()
        assert result["remaining_seconds"] == pytest.approx(seconds, abs=2)
        assert result["remaining_seconds"] < 0
        assert (
            datetime.fromisoformat(result["cancellation_deadline"])
            == seeded.overdue.cancellation_deadline
        )
        assert result["lot"] == {
            "id": str(seeded.overdue.lot_id),
            "slug": "rental-test-lot",
            "name": "Rental test lot",
            "photo_url": "https://static.example.test/lot.jpg",
        }
        assert result["tickets"] == []
        for rental in (seeded.completed, seeded.foreign):
            denied = client.get(f"{ME}/{rental.id}", headers=headers)
            assert denied.status_code == 404
            assert denied.json()["code"] == "not_found"


def test_staff_reads_filter_overlaps_and_return_close_metadata(seeded: SeededRentals) -> None:
    with _client(seeded.tenant) as client:
        assert client.get(ADMIN, headers=_auth(seeded.renter)).status_code == 403
        assert (
            client.get(f"{ADMIN}/{seeded.booked.id}", headers=_auth(seeded.renter)).status_code
            == 403
        )
        headers = _auth(seeded.admin)
        window = {
            "from": seeded.overdue.end_time.isoformat(),
            "to": seeded.booked.start_time.isoformat(),
            "lot_id": str(seeded.booked.lot_id),
            "user_id": str(seeded.renter.id),
        }
        page = client.get(ADMIN, params=window, headers=headers)
        assert page.status_code == 200, page.text
        assert page.headers["Cache-Control"] == "no-store"
        assert page.json()["total"] == 1
        [rental] = page.json()["items"]
        assert rental["id"] == str(seeded.active.id)
        assert rental["version"] == seeded.active.version
        assert rental["user"] == {
            "id": str(seeded.renter.id),
            "name": seeded.renter.name,
            "email": seeded.renter.email,
        }
        empty = client.get(
            ADMIN, params={**window, "user_id": str(seeded.other_renter.id)}, headers=headers
        )
        assert empty.status_code == 200
        assert empty.json()["items"] == []
        invalid = client.get(ADMIN, params={**window, "to": window["from"]}, headers=headers)
        assert invalid.status_code == 422
        naive_from = seeded.overdue.end_time.replace(tzinfo=None).isoformat()
        invalid = client.get(ADMIN, params={**window, "from": naive_from}, headers=headers)
        assert invalid.status_code == 422
        assert "from" in invalid.json()["fields"]

        detail = client.get(f"{ADMIN}/{seeded.completed.id}", headers=_auth(seeded.owner))
        assert detail.status_code == 200, detail.text
        assert (
            datetime.fromisoformat(detail.json()["completed_at"]) == seeded.completed.completed_at
        )
        assert detail.json()["closed_by"] == str(seeded.admin.id)
        assert client.get(f"{ADMIN}/{seeded.foreign.id}", headers=headers).status_code == 404

    with _client(seeded.another_tenant) as client:
        response = client.get(ADMIN, headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == "tenant_mismatch"


def test_calendar_projects_linked_rental_statuses(seeded: SeededRentals) -> None:
    calendar = "/api/v1/admin/calendar"
    period = {
        "from": seeded.completed.start_time.isoformat(),
        "to": seeded.booked.end_time.isoformat(),
    }
    headers = _auth(seeded.admin)
    with _client(seeded.tenant) as client:
        response = client.get(calendar, params=period, headers=headers)
        assert response.status_code == 200, response.text
        assert {event["rental_id"]: event["status"] for event in response.json()} == {
            str(seeded.booked.id): "booked",
            str(seeded.active.id): "active",
            str(seeded.overdue.id): "overdue",
        }
        lot_calendar = client.get(
            f"/api/v1/admin/lots/{seeded.booked.lot_id}/calendar", params=period, headers=headers
        )
        assert lot_calendar.status_code == 200, lot_calendar.text
        assert lot_calendar.json() == response.json()

        for status, rental in (
            ("booked", seeded.booked),
            ("active", seeded.active),
            ("overdue", seeded.overdue),
            ("completed", seeded.completed),
            ("released", seeded.completed),
        ):
            filtered = client.get(calendar, params={**period, "status": status}, headers=headers)
            assert filtered.status_code == 200, filtered.text
            assert [event["rental_id"] for event in filtered.json()] == [str(rental.id)]


def test_admin_rental_date_filters_reject_utc_overflow(seeded: SeededRentals) -> None:
    with _client(seeded.tenant) as client:
        headers = _auth(seeded.owner)
        for bound, value in (
            ("from", "0001-01-01T00:00:00+14:00"),
            ("to", "9999-12-31T23:59:59-14:00"),
        ):
            response = client.get("/api/v1/admin/rentals", headers=headers, params={bound: value})
            assert response.status_code == 422
            assert bound in response.json()["fields"]
