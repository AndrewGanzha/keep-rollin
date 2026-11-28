import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import files
from app.db import configure_session, create_engine, create_session_factory
from app.models import User
from src.domain.entities.outbox_message import OutboxMessage
from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.file_record import FileRecord
from src.infrastructure.postgres.models.idempotency_key_record import IdempotencyKeyRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.verification_request_record import (
    VerificationDocumentRecord,
    VerificationRequestRecord,
)
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
from tests.api.test_files_api import FakeUploadStorage, _post_data

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Requires PostgreSQL")
ME = "/api/v1/me/verification-requests"
ADMIN = "/api/v1/admin/verification-requests"
SESSION = "/api/v1/auth/session"
PURPOSES = ("verification_passport", "verification_registration", "verification_selfie")
PASSPORT = {
    "full_name": "Private Example Applicant",
    "birth_date": "1991-02-03",
    "passport_number": "4321 987654",
    "issued_by": "Private example issuer",
}


@dataclass(frozen=True)
class SeededVerification:
    calendar: SeededCalendarAPI
    user_id: UUID
    other_email: str


@asynccontextmanager
async def database(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    try:
        async with create_session_factory(engine).begin() as session:
            configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_app")
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
def seeded() -> Iterator[SeededVerification]:
    calendar = seed_calendar()
    other_email = f"other-{uuid4().hex}@example.test"

    async def prepare_customer() -> UUID:
        async with database(calendar.tenant_a) as session:
            user = await session.scalar(select(User).where(User.email == calendar.user_a_email))
            assert user is not None
            user.verification_status = "pending"
            session.add(
                User(
                    tenant_id=calendar.tenant_a,
                    email=other_email,
                    name="Other user",
                    password_hash=user.password_hash,
                )
            )
            return user.id

    try:
        yield SeededVerification(calendar, asyncio.run(prepare_customer()), other_email)
    finally:
        cleanup_calendar((calendar.tenant_a, calendar.tenant_b))


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> FakeUploadStorage:
    fixture = FakeUploadStorage()
    monkeypatch.setattr(files, "build_upload_storage", lambda settings: fixture)
    return fixture


def upload(client: TestClient, headers: dict[str, str], purpose: str) -> str:
    response = client.post(files.UPLOAD_PATH, headers=headers, files=_post_data(purpose))
    assert response.status_code == 201, response.text
    return str(response.json()["file_id"])


def uploaded_documents(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    return {purpose: upload(client, headers, purpose) for purpose in PURPOSES}


def idempotent(headers: dict[str, str]) -> dict[str, str]:
    return headers | {"Idempotency-Key": str(uuid4())}


def assert_private_fields_omitted(response: Response) -> None:
    assert response.headers["Cache-Control"] == "no-store"
    assert all(value not in response.text for value in PASSPORT.values())
    assert "signed.example.test" not in response.text
    assert "passport_enc" not in response.text


def test_submission_visibility_and_encrypted_storage(
    seeded: SeededVerification, caplog: pytest.LogCaptureFixture
) -> None:
    calendar = seeded.calendar
    with client_for(calendar.domain_a) as client, client_for(calendar.domain_b) as other_tenant:
        customer = auth(login(client, calendar.user_a_email))
        other = auth(login(client, seeded.other_email))
        staff = auth(login(client, calendar.admin_a_email))
        outsider = auth(login(other_tenant, calendar.owner_b_email))
        documents = uploaded_documents(client, customer)
        headers = idempotent(customer)
        body = {"passport": PASSPORT, "documents": documents}

        assert client.post(ME, json=body).status_code == 401
        assert client.post(ME, headers=customer, json=body).status_code == 422
        assert (
            client.post(
                ME, headers=headers | {"Origin": "https://evil.test"}, json=body
            ).status_code
            == 403
        )
        private_key = PASSPORT["passport_number"]
        invalid = client.post(ME, headers=headers, json=body | {private_key: private_key})
        assert invalid.status_code == 422
        assert_private_fields_omitted(invalid)
        assert private_key not in caplog.text

        created = client.post(ME, headers=headers, json=body)
        assert created.status_code == 201, created.text
        assert_private_fields_omitted(created)
        receipt = created.json()
        request_id = UUID(receipt["id"])
        assert receipt["status"] == "pending" and receipt["version"] == 1
        assert receipt["admin_comment"] is None and receipt["reviewed_at"] is None

        replay = client.post(ME, headers=headers, json=body)
        assert (replay.status_code, replay.content) == (201, created.content)
        assert replay.headers["Idempotent-Replayed"] == "true"
        changed = client.post(
            ME,
            headers=headers,
            json=body | {"passport": PASSPORT | {"passport_number": "4321 987653"}},
        )
        assert changed.status_code == 422 and changed.json()["code"] == "idempotency_conflict"
        assert client.post(ME, headers=idempotent(customer), json=body).status_code == 409
        assert client.post(ME, headers=idempotent(staff), json=body).status_code == 409

        own_list = client.get(ME, headers=customer)
        assert_private_fields_omitted(own_list)
        assert own_list.json() == {"items": [receipt], "total": 1, "limit": 20, "offset": 0}
        assert client.get(ME, headers=other).json()["items"] == []
        assert client.get(f"{ME}/{request_id}", headers=other).status_code == 404
        assert other_tenant.get(f"{ME}/{request_id}", headers=outsider).status_code == 404
        assert other_tenant.get(f"{ADMIN}/{request_id}", headers=outsider).status_code == 404
        assert other_tenant.get(ADMIN, headers=outsider).json()["total"] == 0
        assert client.get(ADMIN, headers=customer).status_code == 403
        assert client.get(f"{ADMIN}/{request_id}", headers=customer).status_code == 403

        queue = client.get(ADMIN, headers=staff, params={"status": "pending", "limit": 1})
        assert_private_fields_omitted(queue)
        assert queue.json()["items"][0]["user"]["id"] == str(seeded.user_id)
        assert queue.json()["total"] == 1 and queue.json()["limit"] == 1
        assert client.get(ADMIN, headers=staff, params={"status": "approved"}).json()["total"] == 0

        mine = client.get(f"{ME}/{request_id}", headers=customer)
        detail = client.get(f"{ADMIN}/{request_id}", headers=staff)
        assert mine.status_code == detail.status_code == 200
        assert mine.headers["Cache-Control"] == detail.headers["Cache-Control"] == "no-store"
        assert "passport" not in mine.json()
        assert detail.json()["passport"] == PASSPORT
        expected_documents = {
            purpose: f"https://signed.example.test/private/{calendar.tenant_a}/{file_id}.jpg"
            for purpose, file_id in documents.items()
        }
        for response in (mine, detail):
            assert {
                doc["purpose"]: doc["url"] for doc in response.json()["documents"]
            } == expected_documents

    async def verify_storage() -> None:
        async with database(calendar.tenant_a) as session:
            encrypted = await session.scalar(
                select(VerificationRequestRecord.passport_enc).where(
                    VerificationRequestRecord.id == request_id
                )
            )
            assert encrypted is not None and encrypted.startswith("v1:")
            assert all(value not in encrypted for value in PASSPORT.values())
            stored_documents = await session.scalars(
                select(VerificationDocumentRecord).where(
                    VerificationDocumentRecord.request_id == request_id
                )
            )
            assert {doc.purpose: str(doc.file_id) for doc in stored_documents} == documents
            cached = await session.scalar(
                select(IdempotencyKeyRecord.response).where(
                    IdempotencyKeyRecord.user_id == seeded.user_id
                )
            )
            assert cached == receipt

    asyncio.run(verify_storage())


def test_submission_rejects_wrong_purpose_owner_tenant_and_readiness(
    seeded: SeededVerification,
) -> None:
    calendar = seeded.calendar
    with client_for(calendar.domain_a) as client, client_for(calendar.domain_b) as other_tenant:
        customer = auth(login(client, calendar.user_a_email))
        other = auth(login(client, seeded.other_email))
        outsider = auth(login(other_tenant, calendar.owner_b_email))
        documents = uploaded_documents(client, customer)
        foreign = upload(other_tenant, outsider, "verification_passport")
        coworker = upload(client, other, "verification_passport")
        pending = UUID(upload(client, customer, "verification_passport"))

        async def make_unready() -> None:
            async with database(calendar.tenant_a) as session:
                await session.execute(
                    update(FileRecord).where(FileRecord.id == pending).values(is_ready=False)
                )

        asyncio.run(make_unready())
        body = {"passport": PASSPORT, "documents": documents}
        headers = idempotent(customer)
        for invalid_id in (
            foreign,
            coworker,
            str(pending),
            str(uuid4()),
            documents["verification_selfie"],
        ):
            invalid = client.post(
                ME,
                headers=headers,
                json=body | {"documents": documents | {"verification_passport": invalid_id}},
            )
            assert invalid.status_code == 422
            assert_private_fields_omitted(invalid)
            assert invalid.json()["fields"] == {
                "documents.verification_passport": "invalid verification document"
            }
            assert invalid_id not in invalid.text
        assert client.get(ME, headers=customer).json()["total"] == 0
        assert client.post(ME, headers=headers, json=body).status_code == 201


def race(
    first: Callable[[], Response], second: Callable[[], Response]
) -> tuple[Response, Response]:
    start = Barrier(2, timeout=10)

    def run(action: Callable[[], Response]) -> Response:
        start.wait()
        return action()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_result = executor.submit(run, first)
        second_result = executor.submit(run, second)
        return first_result.result(), second_result.result()


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_submission_creates_one_request(
    seeded: SeededVerification, same_key: bool
) -> None:
    calendar = seeded.calendar
    with client_for(calendar.domain_a) as client:
        customer = auth(login(client, calendar.user_a_email))
        body = {"passport": PASSPORT, "documents": uploaded_documents(client, customer)}
        first_headers = idempotent(customer)
        second_headers = first_headers if same_key else idempotent(customer)
        first, second = race(
            lambda: client.post(ME, headers=first_headers, json=body),
            lambda: client.post(ME, headers=second_headers, json=body),
        )
        if same_key:
            assert first.status_code == second.status_code == 201
            assert first.content == second.content
            assert {
                first.headers.get("Idempotent-Replayed"),
                second.headers.get("Idempotent-Replayed"),
            } == {None, "true"}
        else:
            assert {first.status_code, second.status_code} == {201, 409}
        assert client.get(ME, headers=customer).json()["total"] == 1


def test_decision_rolls_back_on_outbox_failure_then_allows_one_rejection_and_resubmission(
    seeded: SeededVerification, monkeypatch: pytest.MonkeyPatch
) -> None:
    calendar = seeded.calendar
    with client_for(calendar.domain_a) as client:
        customer = auth(login(client, calendar.user_a_email))
        admin = auth(login(client, calendar.admin_a_email))
        owner = auth(login(client, calendar.owner_a_email))
        body = {"passport": PASSPORT, "documents": uploaded_documents(client, customer)}
        headers = idempotent(customer)
        created = client.post(ME, headers=headers, json=body)
        assert created.status_code == 201, created.text
        request_id = UUID(created.json()["id"])
        path = f"{ADMIN}/{request_id}/decision"
        rejection = {
            "decision": "rejected",
            "comment": "  Upload a clearer picture.  ",
            "version": 1,
        }

        assert client.post(path, headers=customer, json=rejection).status_code == 403
        assert (
            client.post(
                path, headers=owner | {"Sec-Fetch-Site": "cross-site"}, json=rejection
            ).status_code
            == 403
        )
        blank = client.post(path, headers=admin, json=rejection | {"comment": " \n "})
        assert blank.status_code == 422 and blank.json()["fields"] == {
            "comment": "required for rejection"
        }
        stale = client.post(path, headers=admin, json=rejection | {"version": 2})
        assert stale.status_code == 409 and stale.json()["code"] == "stale_version"

        async def reject_outbox(self: OutboxRepository, message: OutboxMessage) -> None:
            raise RuntimeError("Injected outbox failure")

        with monkeypatch.context() as patch:
            patch.setattr(OutboxRepository, "add", reject_outbox)
            failed = client.post(path, headers=admin, json=rejection)
        assert failed.status_code == 500, failed.text
        assert_private_fields_omitted(failed)
        assert (
            client.get(SESSION, headers=customer).json()["user"]["verification_status"] == "pending"
        )
        assert client.get(f"{ME}/{request_id}", headers=customer).json()["version"] == 1

        async def inspect_effects(expected: bool) -> None:
            async with database(calendar.tenant_a) as session:
                audit = (
                    await session.scalars(
                        select(AuditLogRecord).where(AuditLogRecord.entity_id == request_id)
                    )
                ).all()
                messages = (
                    await session.scalars(
                        select(OutboxMessageRecord).where(
                            OutboxMessageRecord.entity_id == request_id
                        )
                    )
                ).all()
                if not expected:
                    assert not audit and not messages
                    return
                assert len(audit) == len(messages) == 1
                assert audit[0].action == "verification.decided"
                assert audit[0].actor_id in (calendar.admin_a_id, calendar.owner_a_id)
                assert audit[0].metadata_json == {"decision": "rejected"}
                assert messages[0].event_type == "verification.rejected"
                assert messages[0].payload == {} and messages[0].user_id == seeded.user_id

        asyncio.run(inspect_effects(False))
        outcomes = race(
            lambda: client.post(path, headers=admin, json=rejection),
            lambda: client.post(path, headers=owner, json=rejection),
        )
        winner, loser = sorted(outcomes, key=lambda response: response.status_code)
        assert winner.status_code == 200, winner.text
        assert_private_fields_omitted(winner)
        assert loser.status_code == 409 and loser.json()["code"] == "already_processed"
        assert (
            client.get(SESSION, headers=customer).json()["user"]["verification_status"]
            == "rejected"
        )
        reviewed = client.get(f"{ME}/{request_id}", headers=customer).json()
        assert reviewed["status"] == "rejected" and reviewed["version"] == 2
        assert reviewed["admin_comment"] == "Upload a clearer picture."
        assert reviewed["reviewed_at"] is not None
        asyncio.run(inspect_effects(True))

        replay = client.post(ME, headers=headers, json=body)
        assert replay.status_code == 201 and replay.content == created.content
        resubmitted = client.post(ME, headers=idempotent(customer), json=body)
        assert resubmitted.status_code == 201 and resubmitted.json()["id"] != str(request_id)
        assert (
            client.get(SESSION, headers=customer).json()["user"]["verification_status"] == "pending"
        )
        current_request_id = resubmitted.json()["id"]
        approved = client.post(
            f"{ADMIN}/{current_request_id}/decision",
            headers=owner,
            json={"decision": "approved", "version": 1},
        )
        assert approved.status_code == 200
        assert (
            client.get(SESSION, headers=customer).json()["user"]["verification_status"]
            == "approved"
        )
        assert client.post(ME, headers=idempotent(customer), json=body).status_code == 409
        history = client.get(ME, headers=customer, params={"limit": 1, "offset": 1}).json()
        assert history["total"] == 2 and history["items"][0]["id"] == str(request_id)
