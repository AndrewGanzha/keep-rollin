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

from app.db import create_engine, create_session_factory
from app.models import User
from src.domain.entities.outbox_message import OutboxMessage
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.idempotency_key_record import IdempotencyKeyRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.ticket_record import TicketRecord
from src.infrastructure.postgres.repositories.outbox_repository import OutboxRepository
from tests.api.test_files_api import UPLOADS, FakeUploadStorage, _post_data
from tests.api.test_files_api import storage as storage
from tests.api.test_rental_reads_api import (
    DATABASE_URL,
    SeededRentals,
    _auth,
    _client,
    seed_rentals,
)

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL integration test")
BODY = {"category": "battery", "description": "Battery stopped responding during the ride."}
MY_TICKETS = "/api/v1/me/tickets"
ADMIN_TICKETS = "/api/v1/admin/tickets"


@pytest.fixture
def seeded() -> Iterator[SeededRentals]:
    yield from seed_rentals()


def _url(rental_id: UUID) -> str:
    return f"/api/v1/me/rentals/{rental_id}/tickets"


def _key(user: User) -> dict[str, str]:
    return _auth(user) | {"Idempotency-Key": str(uuid4())}


def _approve(*people: User) -> None:
    async def approve() -> None:
        assert DATABASE_URL is not None
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine).begin() as session:
                await session.execute(
                    update(User)
                    .where(User.id.in_([person.id for person in people]))
                    .values(verification_status="approved")
                )
        finally:
            await engine.dispose()

    asyncio.run(approve())


def test_ticket_guards_and_partial_photo_save(
    seeded: SeededRentals, storage: FakeUploadStorage
) -> None:
    header = _key(seeded.renter)
    path = _url(seeded.active.id)
    with _client(seeded.tenant) as client:
        missing = client.post(path, headers=_auth(seeded.renter), json=BODY)
        assert missing.status_code == 422
        denied = client.post(path, headers=header, json=BODY)
        assert denied.status_code == 403 and denied.json()["code"] == "verification_required"
        _approve(seeded.renter, seeded.other_renter)
        assert client.post(path, headers=_key(seeded.other_renter), json=BODY).status_code == 404
        assert (
            client.post(
                path, headers=header | {"Origin": "https://foreign.test"}, json=BODY
            ).status_code
            == 403
        )
        invalid = client.post(_url(seeded.booked.id), headers=header, json=BODY)
        assert invalid.status_code == 409 and invalid.json()["code"] == "rental_not_active"
        assert (
            client.post(path, headers=header, json=BODY | {"description": "short"}).status_code
            == 422
        )
        owner_upload = client.post(UPLOADS, headers=header, files=_post_data("ticket_photo"))
        unrelated = client.post(
            UPLOADS, headers=_auth(seeded.other_renter), files=_post_data("ticket_photo")
        )
        assert owner_upload.status_code == unrelated.status_code == 201
        own_id = owner_upload.json()["file_id"]
        foreign_id = unrelated.json()["file_id"]
        invalid_count = client.post(
            path,
            headers=header,
            json=BODY | {"file_ids": [own_id, foreign_id], "photo_upload_failures": 2},
        )
        assert invalid_count.status_code == 422
        body = BODY | {"file_ids": [own_id, foreign_id], "photo_upload_failures": 1}
        response = client.post(path, headers=header, json=body)
        assert response.status_code == 201, response.text
        ticket = response.json()
        assert ticket["status"] == "submitted" and ticket["version"] == 1
        assert ticket["skipped_photo_count"] == 2
        assert set(ticket) == {
            "id",
            "rental_id",
            "status",
            "created_at",
            "skipped_photo_count",
            "version",
        }
        assert BODY["description"] not in response.text
        assert response.headers["Cache-Control"] == "no-store"
        replay = client.post(path, headers=header, json=body)
        assert (
            replay.content == response.content and replay.headers["Idempotent-Replayed"] == "true"
        )
        conflict = client.post(_url(seeded.overdue.id), headers=header, json=body)
        assert conflict.status_code == 422 and conflict.json()["code"] == "idempotency_conflict"
        assert (
            client.post(_url(seeded.overdue.id), headers=_key(seeded.renter), json=BODY).status_code
            == 201
        )

        mine = client.get(MY_TICKETS, headers=header, params={"limit": 1, "status": "submitted"})
        assert mine.status_code == 200 and mine.json()["total"] == 2
        assert mine.json()["items"][0]["photo_urls"] == []
        ticket_path = f"{MY_TICKETS}/{ticket['id']}"
        detail = client.get(ticket_path, headers=header)
        assert detail.status_code == 200
        assert len(detail.json()["photo_urls"]) == 1 and own_id in detail.json()["photo_urls"][0]
        assert detail.headers["Cache-Control"] == "no-store"
        assert client.get(ticket_path, headers=_auth(seeded.other_renter)).status_code == 404
        assert client.get(ticket_path, headers=_auth(seeded.admin)).status_code == 404
        public_staff = client.get(ADMIN_TICKETS, headers=_auth(seeded.admin)).json()
        assert all(item["photo_urls"] == [] for item in public_staff["items"])
        staff_detail = client.get(f"{ADMIN_TICKETS}/{ticket['id']}", headers=_auth(seeded.admin))
        assert staff_detail.status_code == 200
        assert staff_detail.json()["photo_urls"] == detail.json()["photo_urls"]
        rental = client.get(f"/api/v1/me/rentals/{seeded.active.id}", headers=header).json()
        assert [item["id"] for item in rental["tickets"]] == [ticket["id"]]
        assert "photo_urls" not in rental["tickets"][0]


def test_ticket_limit_is_atomic_and_rolling(seeded: SeededRentals) -> None:
    _approve(seeded.renter)
    path = _url(seeded.active.id)
    with _client(seeded.tenant) as client:
        ids = []
        for _ in range(4):
            created = client.post(path, headers=_key(seeded.renter), json=BODY)
            assert created.status_code == 201, created.text
            ids.append(UUID(created.json()["id"]))

    barrier = Barrier(2, timeout=10)

    def report(_: int) -> Response:
        with _client(seeded.tenant) as client:
            barrier.wait()
            return cast(Response, client.post(path, headers=_key(seeded.renter), json=BODY))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(report, range(2)))
    assert sorted(item.status_code for item in results) == [201, 429], [
        item.text for item in results
    ]
    denied = next(item for item in results if item.status_code == 429)
    assert denied.json()["code"] == "issue_limit_exceeded"

    async def age_ticket() -> None:
        assert DATABASE_URL is not None
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine).begin() as session:
                await session.execute(
                    update(TicketRecord)
                    .where(TicketRecord.id == ids[0])
                    .values(created_at=datetime.now(UTC) - timedelta(days=1, seconds=1))
                )
        finally:
            await engine.dispose()

    asyncio.run(age_ticket())
    with _client(seeded.tenant) as client:
        assert client.post(path, headers=_key(seeded.renter), json=BODY).status_code == 201


def test_ticket_outbox_and_audit_rollback(
    seeded: SeededRentals, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approve(seeded.renter)
    header = _key(seeded.renter)
    path = _url(seeded.active.id)
    with _client(seeded.tenant) as client:

        async def fail(self: OutboxRepository, message: OutboxMessage) -> None:
            raise RuntimeError("Injected outbox failure")

        with monkeypatch.context() as patch:
            patch.setattr(OutboxRepository, "add", fail)
            assert client.post(path, headers=header, json=BODY).status_code == 500
        assert client.get(MY_TICKETS, headers=header).json()["items"] == []
        created = client.post(path, headers=header, json=BODY)
        assert created.status_code == 201
        assert client.post(path, headers=header, json=BODY).headers["Idempotent-Replayed"] == "true"
        ticket_id = UUID(created.json()["id"])

    async def check() -> None:
        assert DATABASE_URL is not None
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine)() as session:
                receipt = await session.get(
                    IdempotencyKeyRecord,
                    (seeded.tenant.id, seeded.renter.id, UUID(header["Idempotency-Key"])),
                )
                assert receipt is not None and receipt.response is not None
                assert receipt.response == created.json()
                assert set(receipt.response) == {
                    "id",
                    "rental_id",
                    "status",
                    "created_at",
                    "skipped_photo_count",
                    "version",
                }
                audit_entries = list(
                    await session.scalars(
                        select(AuditLogRecord).where(AuditLogRecord.tenant_id == seeded.tenant.id)
                    )
                )
                assert len(audit_entries) == 1
                entry = audit_entries[0]
                assert entry.actor_role == "user" and entry.action == "ticket.created"
                assert entry.entity_id == ticket_id and entry.metadata_json == {}
                outbox = list(
                    await session.scalars(
                        select(OutboxMessageRecord).where(
                            OutboxMessageRecord.tenant_id == seeded.tenant.id
                        )
                    )
                )
                assert len(outbox) == 2 and {item.user_id for item in outbox} == {
                    seeded.owner.id,
                    seeded.admin.id,
                }
                assert all(
                    item.event_type == "ticket.created.admin"
                    and item.entity_id == ticket_id
                    and not item.payload
                    for item in outbox
                )
        finally:
            await engine.dispose()

    asyncio.run(check())
