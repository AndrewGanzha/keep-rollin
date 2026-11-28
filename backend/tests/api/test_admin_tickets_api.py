import asyncio
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import tickets
from app.db import create_engine, create_session_factory
from app.models import Tenant, User
from src.application.services.outbox import OutboxWriter
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.file_record import FileRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.models.ticket_record import TicketAttachmentRecord, TicketRecord
from tests.api.auth_helpers import enable_mfa
from tests.api.test_admin_calendar_api import cleanup_calendar
from tests.api.test_files_api import FakeUploadStorage
from tests.api.test_rental_reads_api import (
    DATABASE_URL,
    _auth,
    _client,
    _create_lot,
    _create_rental,
)

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")
ADMIN = "/api/v1/admin/tickets"


@dataclass(frozen=True)
class SeededTickets:
    tenant: Tenant
    renter: User
    admin: User
    owner: User
    ticket: TicketRecord
    older_ticket: TicketRecord
    foreign_ticket: TicketRecord
    future_rental: RentalRecord
    photo: FileRecord


@asynccontextmanager
async def _database() -> AsyncIterator[AsyncSession]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    try:
        async with create_session_factory(engine)() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
def seeded() -> Iterator[SeededTickets]:
    suffix = uuid4().hex[:8]
    tenant = Tenant(
        id=uuid4(), name="Tickets", slug=f"tickets-{suffix}", domain=f"tickets-{suffix}.test"
    )
    foreign = Tenant(
        id=uuid4(),
        name="Foreign tickets",
        slug=f"foreign-tickets-{suffix}",
        domain=f"foreign-tickets-{suffix}.test",
    )
    renter = User(
        id=uuid4(), tenant_id=tenant.id, name="Renter", email=f"renter-{suffix}@example.test"
    )
    foreign_renter = User(
        id=uuid4(),
        tenant_id=foreign.id,
        name="Foreign renter",
        email=f"foreign-renter-{suffix}@example.test",
    )
    admin = User(
        id=uuid4(),
        tenant_id=tenant.id,
        role="admin",
        name="Admin",
        email=f"admin-{suffix}@example.test",
    )
    owner = User(
        id=uuid4(),
        tenant_id=tenant.id,
        role="owner",
        name="Owner",
        email=f"owner-{suffix}@example.test",
    )
    enable_mfa(admin)
    enable_mfa(owner)

    async def seed() -> SeededTickets:
        async with _database() as session:
            session.add_all([tenant, foreign])
            await session.flush()
            session.add_all([renter, admin, owner, foreign_renter])
            await session.flush()
            variant = await _create_lot(session, tenant)
            foreign_variant = await _create_lot(session, foreign)
            session.add(
                LotPriceTierRecord(
                    id=uuid4(),
                    tenant_id=tenant.id,
                    variant_id=variant.id,
                    min_units=1,
                    price_per_unit_minor=60_000,
                )
            )
            now = datetime.now(UTC)
            completed = await _create_rental(
                session,
                renter=renter,
                variant=variant,
                start=now - timedelta(days=1),
                status="completed",
                closed_by=admin.id,
            )
            earlier = await _create_rental(
                session,
                renter=renter,
                variant=variant,
                start=now - timedelta(days=2),
                status="completed",
                closed_by=admin.id,
            )
            future = await _create_rental(
                session,
                renter=renter,
                variant=variant,
                start=now + timedelta(days=1),
                status="booked",
            )
            foreign_rental = await _create_rental(
                session,
                renter=foreign_renter,
                variant=foreign_variant,
                start=now - timedelta(hours=1),
                status="active",
            )
            ticket = TicketRecord(
                id=uuid4(),
                tenant_id=tenant.id,
                rental_id=completed.id,
                category="no_power",
                description="The rental stopped switching on.",
                created_at=now,
            )
            older = TicketRecord(
                id=uuid4(),
                tenant_id=tenant.id,
                rental_id=earlier.id,
                category="other",
                description="An earlier issue with this rental.",
                status="in_progress",
                created_at=now - timedelta(days=1),
            )
            foreign_ticket = TicketRecord(
                id=uuid4(),
                tenant_id=foreign.id,
                rental_id=foreign_rental.id,
                category="damage",
                description="A damaged cable near the handlebars.",
                created_at=now,
            )
            photo_id = uuid4()
            photo = FileRecord(
                id=photo_id,
                tenant_id=tenant.id,
                uploaded_by=renter.id,
                purpose="ticket_photo",
                object_key=f"{tenant.id}/{photo_id}.jpg",
                content_type="image/jpeg",
                size_bytes=42,
                is_ready=True,
            )
            session.add_all([ticket, older, foreign_ticket, photo])
            await session.flush()
            session.add(
                TicketAttachmentRecord(
                    tenant_id=tenant.id, ticket_id=ticket.id, file_id=photo.id, position=0
                )
            )
            await session.commit()
            return SeededTickets(
                tenant, renter, admin, owner, ticket, older, foreign_ticket, future, photo
            )

    try:
        yield asyncio.run(seed())
    finally:
        cleanup_calendar((tenant.id, foreign.id))


def _staff_headers(seeded: SeededTickets, actor: User) -> dict[str, str]:
    return {
        **_auth(actor),
        "Origin": f"https://{seeded.tenant.domain}",
        "Sec-Fetch-Site": "same-origin",
    }


def test_staff_queue_enforces_scope_filters_and_signs_photos_only_on_detail(
    seeded: SeededTickets, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = FakeUploadStorage()
    signed: list[str] = []
    original = storage.signed_url

    async def sign(key: str, *, public: bool) -> str:
        assert not public
        signed.append(key)
        return await original(key, public=public)

    monkeypatch.setattr(storage, "signed_url", sign)
    monkeypatch.setattr(tickets, "get_upload_storage", lambda request: storage)
    headers = _auth(seeded.admin)
    path = f"{ADMIN}/{seeded.ticket.id}"
    with _client(seeded.tenant) as client:
        assert client.get(ADMIN).status_code == 401
        assert client.get(ADMIN, headers=_auth(seeded.renter)).status_code == 403
        assert client.get(path, headers=_auth(seeded.renter)).status_code == 403
        assert client.get(f"{ADMIN}/{seeded.foreign_ticket.id}", headers=headers).status_code == 404

        response = client.get(ADMIN, headers=headers, params={"limit": 1, "offset": 1})
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        page = response.json()
        assert (page["total"], page["limit"], page["offset"]) == (2, 1, 1)
        assert [item["id"] for item in page["items"]] == [str(seeded.older_ticket.id)]

        window = {
            "from": seeded.ticket.created_at.isoformat(),
            "to": (seeded.ticket.created_at + timedelta(minutes=1)).isoformat(),
            "status": "submitted",
            "lot_id": str(seeded.future_rental.lot_id),
            "rental_id": str(seeded.ticket.rental_id),
        }
        response = client.get(ADMIN, params=window, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1
        [summary] = response.json()["items"]
        assert summary["id"] == str(seeded.ticket.id)
        assert summary["photo_urls"] == []
        assert summary["user"]["id"] == str(seeded.renter.id)
        assert signed == []
        assert (
            client.get(ADMIN, params={"to": window["from"]}, headers=headers).json()["total"] == 1
        )
        assert (
            client.get(ADMIN, params={**window, "to": window["from"]}, headers=headers).status_code
            == 422
        )
        assert (
            client.get(ADMIN, params={"lot_id": str(uuid4())}, headers=headers).json()["total"] == 0
        )

        detail = client.get(path, headers=_auth(seeded.owner))
        assert detail.status_code == 200, detail.text
        assert detail.headers["Cache-Control"] == "no-store"
        assert detail.json()["photo_urls"] == [
            f"https://signed.example.test/private/{seeded.photo.object_key}"
        ]
        assert signed == [seeded.photo.object_key]


def test_staff_ticket_transition_audits_and_notifies_once(seeded: SeededTickets) -> None:
    path = f"{ADMIN}/{seeded.ticket.id}"
    headers = _staff_headers(seeded, seeded.admin)
    taking = {"status": "in_progress", "version": 1}
    with _client(seeded.tenant) as client:
        request_without_csrf = client.build_request(
            "PATCH", path, json=taking, headers=_auth(seeded.admin)
        )
        request_without_csrf.headers.pop("Origin", None)
        request_without_csrf.headers.pop("Sec-Fetch-Site", None)
        missing_csrf = client.send(request_without_csrf)
        assert missing_csrf.status_code == 403
        skip = client.patch(
            path, json={**taking, "status": "resolved", "admin_comment": "Fixed"}, headers=headers
        )
        assert (skip.status_code, skip.json()["code"]) == (409, "validation_error")

        with ThreadPoolExecutor(max_workers=2) as workers:
            calls = [
                workers.submit(client.patch, path, json=taking, headers=headers) for _ in range(2)
            ]
            accepted, stale = sorted(
                (call.result() for call in calls), key=lambda response: response.status_code
            )
        assert (accepted.status_code, stale.status_code) == (200, 409)
        assert accepted.json()["version"] == 2
        assert accepted.json()["photo_urls"] == []
        assert stale.json()["code"] == "stale_version"
        repeat = client.patch(path, json={**taking, "version": 2}, headers=headers)
        assert (repeat.status_code, repeat.json()["code"]) == (409, "validation_error")

        resolving = {"status": "resolved", "version": 2}
        invalid = client.patch(path, json={**resolving, "admin_comment": "   "}, headers=headers)
        assert invalid.status_code == 422
        assert "admin_comment" in invalid.json()["fields"]
        resolved = client.patch(
            path, json={**resolving, "admin_comment": "  Repaired cable  "}, headers=headers
        )
        assert resolved.status_code == 200, resolved.text
        result = resolved.json()
        assert result["version"] == 3
        assert result["admin_comment"] == "Repaired cable"
        assert result["status"] == "resolved"
        assert result["updated_at"] == result["resolved_at"]

    async def effects() -> None:
        async with _database() as session:
            audit = await session.scalars(
                select(AuditLogRecord)
                .where(AuditLogRecord.entity_id == seeded.ticket.id)
                .order_by(AuditLogRecord.created_at)
            )
            assert [(row.action, row.actor_id, row.metadata_json) for row in audit] == [
                (
                    "ticket.status_changed",
                    seeded.admin.id,
                    {"old_status": "submitted", "new_status": "in_progress"},
                ),
                (
                    "ticket.status_changed",
                    seeded.admin.id,
                    {"old_status": "in_progress", "new_status": "resolved"},
                ),
            ]
            outbox = await session.scalars(
                select(OutboxMessageRecord).where(OutboxMessageRecord.entity_id == seeded.ticket.id)
            )
            assert {(row.event_type, row.user_id) for row in outbox} == {
                ("ticket.updated.user", seeded.renter.id),
                ("ticket.resolved.user", seeded.renter.id),
            }

    asyncio.run(effects())


@pytest.mark.parametrize("expired", [False, True])
def test_timed_maintenance_preserves_reservations_and_releases_history(
    seeded: SeededTickets, expired: bool
) -> None:
    now = datetime.now(UTC)
    until = now + timedelta(hours=4)
    lot_id = seeded.future_rental.lot_id
    headers = _staff_headers(seeded, seeded.admin)
    owner_headers = _staff_headers(seeded, seeded.owner)
    body = {
        "status": "in_progress",
        "version": 1,
        "put_lot_maintenance": True,
        "maintenance_until": until.isoformat(),
    }
    with _client(seeded.tenant) as client:
        response = client.patch(f"{ADMIN}/{seeded.ticket.id}", json=body, headers=headers)
        assert response.status_code == 200, response.text
        lot = client.get(f"/api/v1/admin/lots/{lot_id}", headers=owner_headers)
        assert lot.status_code == 200, lot.text
        assert (lot.json()["status"], lot.json()["version"]) == ("maintenance", 2)
        query = {
            "from": (now - timedelta(minutes=1)).isoformat(),
            "to": seeded.future_rental.end_time.isoformat(),
            "lot_id": str(lot_id),
        }
        events = client.get("/api/v1/admin/calendar", params=query, headers=headers)
        assert events.status_code == 200, events.text
        maintenance, future = events.json()
        assert maintenance["kind"] == "maintenance"
        assert datetime.fromisoformat(maintenance["end_time"]) == until
        assert future["rental_id"] == str(seeded.future_rental.id)
        assert future["status"] == "booked"

        async def expire_block() -> None:
            async with _database() as session:
                await session.execute(
                    update(OccupancyRecord)
                    .where(OccupancyRecord.id == UUID(maintenance["id"]))
                    .values(
                        period=Range(
                            now - timedelta(hours=2), now - timedelta(hours=1), bounds="[)"
                        )
                    )
                )
                await session.commit()

        if expired:
            asyncio.run(expire_block())
        reopened = client.post(
            f"/api/v1/admin/lots/{lot_id}/status", json={"status": "active"}, headers=owner_headers
        )
        assert reopened.status_code == 200, reopened.text
        assert (reopened.json()["status"], reopened.json()["version"]) == ("active", 3)

    async def history() -> None:
        async with _database() as session:
            record = await session.get(OccupancyRecord, UUID(maintenance["id"]))
            assert record is not None
            assert record.ref_id == lot_id
            end = record.period.upper
            assert end is not None
            if expired:
                assert record.status == "active"
                assert end == now - timedelta(hours=1)
            else:
                assert record.status == "released"
                assert now < end < until
            audit = await session.scalar(
                select(AuditLogRecord).where(
                    AuditLogRecord.entity_id == lot_id, AuditLogRecord.actor_id == seeded.admin.id
                )
            )
            assert audit is not None
            assert audit.action == "lot.status_changed"
            assert audit.metadata_json == {"old_status": "active", "new_status": "maintenance"}

    asyncio.run(history())


def test_maintenance_rejects_conflicts_overdue_and_invalid_date(seeded: SeededTickets) -> None:
    path = f"{ADMIN}/{seeded.ticket.id}"
    headers = _staff_headers(seeded, seeded.admin)
    taking = {"status": "in_progress", "version": 1}
    with _client(seeded.tenant) as client:
        invalid_dates: list[dict[str, object]] = [
            {"put_lot_maintenance": True},
            {"maintenance_until": seeded.future_rental.end_time.isoformat()},
            {
                "put_lot_maintenance": True,
                "maintenance_until": seeded.ticket.created_at.isoformat(),
            },
            {"put_lot_maintenance": True, "maintenance_until": "2030-07-01T12:00:00"},
        ]
        for fields in invalid_dates:
            invalid = client.patch(path, json={**taking, **fields}, headers=headers)
            assert invalid.status_code == 422, invalid.text
            assert "maintenance_until" in invalid.json()["fields"]

        maintenance = {
            **taking,
            "put_lot_maintenance": True,
            "maintenance_until": seeded.future_rental.end_time.isoformat(),
        }
        rejected = client.patch(path, json=maintenance, headers=headers)
        assert (rejected.status_code, rejected.json()["code"]) == (409, "slot_taken")

        async def mark_lot_overdue() -> None:
            async with _database() as session:
                lot = await session.get(LotRecord, seeded.future_rental.lot_id)
                assert lot is not None
                assert (lot.status, lot.version) == ("active", 1)
                lot.status = "overdue"
                await session.commit()

        asyncio.run(mark_lot_overdue())
        blocked = client.patch(path, json=maintenance, headers=headers)
        assert (blocked.status_code, blocked.json()["code"]) == (409, "lot_unavailable")
        ticket = client.get(ADMIN, params={"status": "submitted"}, headers=headers).json()["items"][
            0
        ]
        assert ticket["id"] == str(seeded.ticket.id)
        assert ticket["version"] == 1


def test_staff_transition_rolls_back_if_outbox_fails(
    seeded: SeededTickets, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_enqueue(self: OutboxWriter, **fields: object) -> None:
        raise HTTPException(503, detail={"code": "service_unavailable"})

    monkeypatch.setattr(OutboxWriter, "enqueue", fail_enqueue)
    headers = _staff_headers(seeded, seeded.admin)
    body = {
        "status": "in_progress",
        "version": 1,
        "put_lot_maintenance": True,
        "maintenance_until": (datetime.now(UTC) + timedelta(hours=4)).isoformat(),
    }
    with _client(seeded.tenant) as client:
        response = client.patch(f"{ADMIN}/{seeded.ticket.id}", json=body, headers=headers)
        assert response.status_code == 503, response.text

    async def effects() -> None:
        async with _database() as session:
            lot = await session.get(LotRecord, seeded.future_rental.lot_id)
            ticket = await session.get(TicketRecord, seeded.ticket.id)
            assert lot is not None and (lot.status, lot.version) == ("active", 1)
            assert ticket is not None and (ticket.status, ticket.version) == ("submitted", 1)
            assert (
                await session.scalar(
                    select(OccupancyRecord).where(
                        OccupancyRecord.lot_id == lot.id, OccupancyRecord.kind == "maintenance"
                    )
                )
                is None
            )
            assert (
                await session.scalar(
                    select(AuditLogRecord).where(AuditLogRecord.entity_id.in_((lot.id, ticket.id)))
                )
                is None
            )

    asyncio.run(effects())
