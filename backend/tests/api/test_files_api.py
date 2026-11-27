import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.api import files
from app.config import Settings
from app.db import configure_session, create_engine, create_session_factory
from src.application.services.uploads import PreparedUpload, StorageUnavailableError
from src.infrastructure.postgres.models.file_record import FileRecord
from src.infrastructure.postgres.repositories.file_repository import (
    FileRepository,
    UnknownLotPhotoError,
)
from tests.api.test_admin_calendar_api import (
    DATABASE_URL,
    SeededCalendarAPI,
    auth,
    cleanup_calendar,
    client_for,
    login,
    seed_calendar,
)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
UPLOADS = "/api/v1/files"


class FakeUploadStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[bool, str], PreparedUpload] = {}
        self.fail_put = False
        self.fail_delete = False

    async def put(self, key: str, upload: PreparedUpload, *, public: bool) -> None:
        self.objects[public, key] = upload
        if self.fail_put:
            raise StorageUnavailableError("fixture write failure after putting the object")

    async def signed_url(self, key: str, *, public: bool) -> str:
        return f"https://signed.example.test/{'public' if public else 'private'}/{key}"

    async def delete(self, key: str, *, public: bool) -> None:
        if self.fail_delete:
            raise StorageUnavailableError("fixture delete failure")
        self.objects.pop((public, key), None)

    def public_url(self, key: str) -> str:
        return f"https://public.example.test/{key}"


@pytest.fixture
def seeded() -> Iterator[SeededCalendarAPI]:
    value = seed_calendar()
    try:
        yield value
    finally:
        cleanup_calendar((value.tenant_a, value.tenant_b))


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> FakeUploadStorage:
    fixture = FakeUploadStorage()

    def build(settings: Settings) -> FakeUploadStorage:
        return fixture

    monkeypatch.setattr(files, "build_upload_storage", build)
    monkeypatch.setattr(cli, "build_upload_storage", build)
    return fixture


def _jpeg() -> bytes:
    image = Image.new("RGB", (4, 6), "red")
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private image description"
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def _post_data(
    purpose: str, data: bytes | None = None
) -> dict[str, tuple[str | None, bytes | str, str]]:
    return {
        "purpose": (None, purpose, "text/plain"),
        "file": ("private-filename.jpg", _jpeg() if data is None else data, "image/jpeg"),
    }


def test_upload_permissions_mime_limit_and_private_objects(
    seeded: SeededCalendarAPI, storage: FakeUploadStorage
) -> None:
    with client_for(seeded.domain_a) as client:
        assert client.post(UPLOADS, files=_post_data("ticket_photo")).status_code == 401
        user = auth(login(client, seeded.user_a_email))
        owner = auth(login(client, seeded.owner_a_email))
        assert client.post(UPLOADS, headers=user, files=_post_data("lot_photo")).status_code == 403
        csrf = client.post(
            UPLOADS,
            headers={**owner, "Origin": f"https://{seeded.domain_b}"},
            files=_post_data("lot_photo"),
        )
        assert csrf.status_code == 403
        bad = client.post(UPLOADS, headers=owner, files=_post_data("lot_photo", b"not an image"))
        assert bad.status_code == 422 and bad.json()["code"] == "upload_invalid"
        too_large = client.post(
            UPLOADS, headers=owner, files=_post_data("lot_photo", b"x" * (5 * 1024 * 1024 + 1))
        )
        assert too_large.status_code == 413 and too_large.json()["code"] == "payload_too_large"
        transport_limit = client.post(
            UPLOADS,
            headers=owner,
            files=_post_data("ticket_photo", b"x" * files.MAX_MULTIPART_BYTES),
        )
        assert transport_limit.status_code == 413
        assert transport_limit.headers["Content-Type"] == "application/problem+json"
        assert transport_limit.json()["code"] == "payload_too_large"
        assert transport_limit.json()["trace_id"] == transport_limit.headers["X-Request-Id"]

        def multipart_stream() -> Iterator[bytes]:
            yield (
                b'--limit\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nticket_photo\r\n'
            )
            yield (
                b'--limit\r\nContent-Disposition: form-data; name="file"; filename="sample.jpg"\r\n'
                b"Content-Type: image/jpeg\r\n\r\n"
            )
            yield b"x" * files.MAX_MULTIPART_BYTES
            yield b"\r\n--limit--\r\n"

        streamed = client.post(
            UPLOADS,
            headers={**owner, "Content-Type": "multipart/form-data; boundary=limit"},
            content=multipart_stream(),
        )
        assert streamed.status_code == 413
        assert streamed.headers["Content-Type"] == "application/problem+json"
        assert streamed.json()["code"] == "payload_too_large"
        assert streamed.json()["trace_id"] == streamed.headers["X-Request-Id"]
        assert not storage.objects

        photo = client.post(UPLOADS, headers=owner, files=_post_data("lot_photo"))
        doc = client.post(UPLOADS, headers=user, files=_post_data("verification_registration"))
        for result in (photo, doc):
            assert result.status_code == 201, result.text
            assert result.headers["Cache-Control"] == "no-store"
            assert set(result.json()) == {"file_id", "url"}

        doc_id = UUID(doc.json()["file_id"])
        photo_id = UUID(photo.json()["file_id"])
        assert doc.json()["url"].endswith(f"/private/{seeded.tenant_a}/{doc_id}.jpg")
        assert photo.json()["url"].endswith(f"/public/{seeded.tenant_a}/{photo_id}.jpg")
        assert len(storage.objects) == 2
        image = storage.objects[True, f"{seeded.tenant_a}/{photo_id}.jpg"]
        with Image.open(BytesIO(image.data)) as content:
            assert content.size == (6, 4)
            assert not content.getexif()

    async def verify_rls_and_attachment_guards() -> None:
        assert DATABASE_URL is not None
        engine = create_engine(DATABASE_URL)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                configure_session(
                    session, tenant_id=seeded.tenant_b, database_role="keep_rollin_app"
                )
                assert list(await session.scalars(select(FileRecord.id))) == []
                with pytest.raises(UnknownLotPhotoError):
                    await FileRepository(session).set_lot_photos(
                        lot_id=seeded.lot_a_id, file_ids=[photo_id]
                    )
            async with factory.begin() as session:
                configure_session(
                    session, tenant_id=seeded.tenant_a, database_role="keep_rollin_app"
                )
                repository = FileRepository(session)
                assert sorted(await session.scalars(select(FileRecord.id))) == sorted(
                    [doc_id, photo_id]
                )
                with pytest.raises(UnknownLotPhotoError):
                    await repository.set_lot_photos(lot_id=seeded.lot_a_id, file_ids=[doc_id])
                urls = await repository.set_lot_photos(lot_id=seeded.lot_a_id, file_ids=[photo_id])
                assert urls == [f"https://public.example.test/{seeded.tenant_a}/{photo_id}.jpg"]
        finally:
            await engine.dispose()

    asyncio.run(verify_rls_and_attachment_guards())


def test_orphan_purge_preserves_links_and_recovers_storage_failures(
    seeded: SeededCalendarAPI,
    storage: FakeUploadStorage,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert DATABASE_URL is not None
    dsn = DATABASE_URL
    monkeypatch.setenv("PROVISION_DATABASE_URL", dsn)
    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        linked = client.post(UPLOADS, headers=owner, files=_post_data("lot_photo"))
        assert linked.status_code == 201, linked.text
        storage.fail_put = True
        failed = client.post(UPLOADS, headers=owner, files=_post_data("verification_passport"))
        assert failed.status_code == 503 and failed.json()["code"] == "service_unavailable"
        assert len(storage.objects) == 2
    linked_id = UUID(linked.json()["file_id"])

    async def age_files() -> UUID:
        engine = create_engine(dsn)
        try:
            async with create_session_factory(engine).begin() as session:
                configure_session(
                    session, tenant_id=seeded.tenant_a, database_role="keep_rollin_app"
                )
                await session.execute(
                    update(FileRecord).values(created_at=datetime.now(UTC) - timedelta(days=2))
                )
                failed_record = await session.scalar(
                    select(FileRecord).where(FileRecord.id != linked_id)
                )
                assert failed_record is not None and not failed_record.is_ready
                await FileRepository(session).set_lot_photos(
                    lot_id=seeded.lot_a_id, file_ids=[linked_id]
                )
                return failed_record.id
        finally:
            await engine.dispose()

    failed_id = asyncio.run(age_files())
    assert cli.main(["purge-orphan-uploads"]) == 0
    assert "dry-run: 1 orphan uploads" in capsys.readouterr().out
    storage.fail_delete = True
    assert cli.main(["purge-orphan-uploads", "--execute"]) == 1
    assert "object storage unavailable" in capsys.readouterr().err
    assert len(storage.objects) == 2
    storage.fail_delete = False
    assert cli.main(["purge-orphan-uploads", "--execute", "--batch-size", "1"]) == 0
    assert "purged 1 orphan uploads" in capsys.readouterr().out
    assert list(storage.objects) == [(True, f"{seeded.tenant_a}/{linked_id}.jpg")]
    assert (False, f"{seeded.tenant_a}/{failed_id}.jpg") not in storage.objects
    assert cli.main(["purge-orphan-uploads", "--execute"]) == 0
    assert "purged 0 orphan uploads" in capsys.readouterr().out


def test_upload_rejects_reservation_already_claimed_for_purge(
    seeded: SeededCalendarAPI,
    storage: FakeUploadStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DATABASE_URL is not None
    dsn = DATABASE_URL
    original_commit = AsyncSession.commit

    async def commit_and_claim(session: AsyncSession) -> None:
        pending = next((row for row in session.new if isinstance(row, FileRecord)), None)
        await original_commit(session)
        if pending is not None:
            engine = create_engine(dsn)
            try:
                async with create_session_factory(engine).begin() as other:
                    await other.execute(
                        update(FileRecord)
                        .where(FileRecord.id == pending.id)
                        .values(is_purging=True)
                    )
            finally:
                await engine.dispose()

    monkeypatch.setattr(AsyncSession, "commit", commit_and_claim)
    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        result = client.post(UPLOADS, headers=owner, files=_post_data("lot_photo"))
    assert result.status_code == 503
    assert result.json()["code"] == "service_unavailable"
    assert storage.objects == {}
