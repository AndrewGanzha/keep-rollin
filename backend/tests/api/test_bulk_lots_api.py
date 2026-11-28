import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid1, uuid4

import pytest
from sqlalchemy import func, select, update

from app.db import create_engine, create_session_factory
from src.infrastructure.postgres.models.file_record import AttachmentRecord
from src.infrastructure.postgres.models.idempotency_key_record import IdempotencyKeyRecord
from tests.api.test_admin_categories_api import (
    DATABASE_URL,
    SeededAdminCategories,
    auth,
    client_for,
    login,
)
from tests.api.test_admin_lots_api import LOTS, PHOTO, payload
from tests.api.test_admin_lots_api import seeded as seeded
from tests.api.test_files_api import UPLOADS, FakeUploadStorage, _post_data
from tests.api.test_files_api import storage as storage

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
BULK_LOTS = f"{LOTS}/bulk"


def test_bulk_lots_require_owner_csrf_and_valid_input(seeded: SeededAdminCategories) -> None:
    template = payload(seeded.active_category_id)
    body = {"template": template, "count": 2}
    key = {"Idempotency-Key": str(uuid4())}
    with client_for(seeded.domain_a) as client:
        assert client.post(BULK_LOTS, headers=key, json=body).status_code == 401
        for email in (seeded.admin_a_email, seeded.user_a_email):
            headers = auth(login(client, email)) | key
            assert client.post(BULK_LOTS, headers=headers, json=body).status_code == 403

        owner = auth(login(client, seeded.owner_a_email))
        for bad_key in ({}, {"Idempotency-Key": "invalid"}, {"Idempotency-Key": str(uuid1())}):
            response = client.post(BULK_LOTS, headers=owner | bad_key, json=body)
            assert response.status_code == 422, response.text
        for count in (0, 51, True, "2", 1.5):
            response = client.post(BULK_LOTS, headers=owner | key, json=body | {"count": count})
            assert response.status_code == 422, response.text
            assert "count" in response.json()["fields"]

        invalid_template = template | {"allowed_durations": [7, 7]}
        invalid = client.post(
            BULK_LOTS, headers=owner | key, json=body | {"template": invalid_template}
        )
        assert invalid.status_code == 422, invalid.text
        assert "allowed_durations.1" in invalid.json()["fields"]
        foreign_category = template | {"category_id": str(seeded.category_b_id)}
        foreign = client.post(
            BULK_LOTS, headers=owner | key, json=body | {"template": foreign_category}
        )
        assert foreign.status_code == 404, foreign.text
        assert client.get(LOTS, headers=owner).json()["total"] == 1

    with client_for(seeded.domain_a, browser_headers=False) as client:
        response = client.post(BULK_LOTS, headers=owner | key, json=body)
        assert response.status_code == 403, response.text


def test_bulk_lots_clone_attachments_and_replay_result(
    seeded: SeededAdminCategories, storage: FakeUploadStorage
) -> None:
    template = payload(seeded.active_category_id) | {"status": "archived"}
    template.pop("photos")
    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        uploads = [
            client.post(UPLOADS, headers=owner, files=_post_data("lot_photo")) for _ in range(2)
        ]
        for upload in uploads:
            assert upload.status_code == 201, upload.text
        file_ids = [upload.json()["file_id"] for upload in uploads]
        template["file_ids"] = file_ids
        headers = owner | {"Idempotency-Key": str(uuid4())}
        body = {"template": template, "count": 3}
        missing_photo = body | {"template": template | {"file_ids": [str(uuid4())]}}
        missing = client.post(BULK_LOTS, headers=headers, json=missing_photo)
        assert missing.status_code == 404, missing.text

        created = client.post(BULK_LOTS, headers=headers, json=body)
        assert created.status_code == 201, created.text
        assert created.headers["Cache-Control"] == "no-store"
        assert "Idempotent-Replayed" not in created.headers
        items = created.json()["items"]
        for number, item in enumerate(items, 1):
            assert item["name"] == f"Городской велосипед №{number}"
            assert item["slug"] == f"gorodskoy-velosiped-{number}"
            assert item["status"] == "archived"
            assert item["photos"] == [
                storage.public_url(f"{seeded.tenant_a}/{file_id}.jpg") for file_id in file_ids
            ]
            assert item["price_from"]["amount_minor"] == 4200
            assert client.get(f"{LOTS}/{item['id']}", headers=owner).json() == item
        assert len({item["id"] for item in items}) == 3

        replayed = client.post(BULK_LOTS, headers=headers, json=body)
        assert replayed.status_code == 201
        assert replayed.headers["Idempotent-Replayed"] == "true"
        assert replayed.content == created.content
        conflict = client.post(BULK_LOTS, headers=headers, json=body | {"count": 2})
        assert conflict.status_code == 422
        assert conflict.json()["code"] == "idempotency_conflict"
        assert client.get(LOTS, headers=owner).json()["total"] == 4

    async def check_links() -> None:
        assert DATABASE_URL is not None
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine)() as session:
                attachments = await session.scalars(
                    select(AttachmentRecord).where(AttachmentRecord.tenant_id == seeded.tenant_a)
                )
                assert {
                    (str(row.lot_id), str(row.file_id), row.position) for row in attachments
                } == {
                    (item["id"], file_id, position)
                    for item in items
                    for position, file_id in enumerate(file_ids)
                }
        finally:
            await engine.dispose()

    asyncio.run(check_links())


def test_bulk_lots_accept_maximum_count_and_keep_suffixes(seeded: SeededAdminCategories) -> None:
    template = payload(seeded.active_category_id) | {"name": "Ж" * 120, "slug": "x" * 80}
    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        headers = owner | {"Idempotency-Key": str(uuid4())}
        created = client.post(BULK_LOTS, headers=headers, json={"template": template, "count": 50})
        assert created.status_code == 201, created.text
        items = created.json()["items"]
        assert len(items) == 50
        for number, item in enumerate(items, 1):
            number_width = len(str(number))
            assert item["name"] == "Ж" * (118 - number_width) + f" №{number}"
            assert item["slug"] == "x" * (79 - number_width) + f"-{number}"
            assert item["photos"] == [PHOTO]
        assert client.get(LOTS, headers=owner).json()["total"] == 51


def test_bulk_lots_roll_back_on_second_insert_and_allow_retry(
    seeded: SeededAdminCategories,
) -> None:
    template = payload(seeded.active_category_id) | {"slug": "batch"}
    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        existing = client.post(LOTS, headers=owner, json=template | {"slug": "batch-2"})
        assert existing.status_code == 201, existing.text
        existing_id = existing.json()["id"]
        headers = owner | {"Idempotency-Key": str(uuid4())}
        body = {"template": template, "count": 3}
        failed = client.post(BULK_LOTS, headers=headers, json=body)
        assert failed.status_code == 409, failed.text
        assert failed.json()["code"] == "slug_taken"
        remaining = client.get(LOTS, headers=owner).json()
        assert {lot["slug"] for lot in remaining["items"]} == {seeded.lot_slug, "batch-2"}

        updated = client.patch(
            f"{LOTS}/{existing_id}", headers=owner, json={"version": 1, "slug": "existing"}
        )
        assert updated.status_code == 200, updated.text
        retried = client.post(BULK_LOTS, headers=headers, json=body)
        assert retried.status_code == 201, retried.text
        assert "Idempotent-Replayed" not in retried.headers
        assert [item["slug"] for item in retried.json()["items"]] == [
            "batch-1",
            "batch-2",
            "batch-3",
        ]


def test_concurrent_bulk_request_with_same_key_creates_one_batch(
    seeded: SeededAdminCategories,
) -> None:
    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        headers = owner | {"Idempotency-Key": str(uuid4())}
        body = {"template": payload(seeded.active_category_id), "count": 1}
        start = Barrier(2, timeout=10)

        def submit() -> tuple[int, str | None, bytes]:
            start.wait()
            response = client.post(BULK_LOTS, headers=headers, json=body)
            return (
                response.status_code,
                response.headers.get("Idempotent-Replayed"),
                response.content,
            )

        with ThreadPoolExecutor(max_workers=2) as requests:
            first_request = requests.submit(submit)
            second_request = requests.submit(submit)
            first, second = first_request.result(), second_request.result()
        assert first[0] == second[0] == 201, (first, second)
        assert first[2] == second[2]
        assert {first[1], second[1]} == {None, "true"}
        assert client.get(LOTS, headers=owner).json()["total"] == 2


def test_bulk_lots_reuse_expired_idempotency_key(seeded: SeededAdminCategories) -> None:
    key = uuid4()

    async def expire_key() -> None:
        assert DATABASE_URL is not None
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine).begin() as session:
                await session.execute(
                    update(IdempotencyKeyRecord)
                    .where(
                        IdempotencyKeyRecord.tenant_id == seeded.tenant_a,
                        IdempotencyKeyRecord.key == key,
                    )
                    .values(expires_at=func.clock_timestamp() - timedelta(seconds=1))
                )
        finally:
            await engine.dispose()

    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        headers = owner | {"Idempotency-Key": str(key)}
        template = payload(seeded.active_category_id)
        first = client.post(BULK_LOTS, headers=headers, json={"template": template, "count": 1})
        assert first.status_code == 201, first.text
        asyncio.run(expire_key())

        another_template = template | {"name": "Another model"}
        body = {"template": another_template, "count": 1}
        created = client.post(BULK_LOTS, headers=headers, json=body)
        assert created.status_code == 201, created.text
        assert "Idempotent-Replayed" not in created.headers
        assert created.json()["items"][0]["name"] == "Another model №1"
        assert client.get(LOTS, headers=owner).json()["total"] == 3

        replay = client.post(BULK_LOTS, headers=headers, json=body)
        assert replay.status_code == 201, replay.text
        assert replay.headers["Idempotent-Replayed"] == "true"
        assert replay.content == created.content
