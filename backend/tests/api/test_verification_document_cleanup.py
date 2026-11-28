import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.sql.elements import ColumnElement

from app import cli
from app.db import configure_session, create_engine, create_session_factory
from app.models import User
from src.infrastructure.postgres.models.file_record import FileRecord
from src.infrastructure.postgres.repositories.file_repository import FileRepository
from tests.api.test_admin_calendar_api import (
    DATABASE_URL,
    SeededCalendarAPI,
    auth,
    client_for,
    login,
)
from tests.api.test_files_api import FakeUploadStorage, _post_data, seeded, storage  # noqa: F401

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL integration test")


def test_orphan_purge_preserves_attached_verification_documents(
    seeded: SeededCalendarAPI,  # noqa: F811
    storage: FakeUploadStorage,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert DATABASE_URL is not None
    dsn = DATABASE_URL
    monkeypatch.setenv("PROVISION_DATABASE_URL", dsn)

    class FixtureFileRepository(FileRepository):
        @staticmethod
        def _unattached_before(cutoff: datetime) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
            old_enough, unattached = FileRepository._unattached_before(cutoff)
            return old_enough & (FileRecord.tenant_id == seeded.tenant_a), unattached

    monkeypatch.setattr(cli, "FileRepository", FixtureFileRepository)

    purposes = ("verification_passport", "verification_registration", "verification_selfie")

    async def prepare_user() -> None:
        engine = create_engine(dsn)
        try:
            async with create_session_factory(engine).begin() as session:
                configure_session(
                    session, tenant_id=seeded.tenant_a, database_role="keep_rollin_app"
                )
                await session.execute(
                    update(User)
                    .where(User.email == seeded.user_a_email)
                    .values(verification_status="pending")
                )
        finally:
            await engine.dispose()

    asyncio.run(prepare_user())
    with client_for(seeded.domain_a) as client:
        headers = auth(login(client, seeded.user_a_email))
        documents = {}
        for purpose in purposes:
            uploaded = client.post("/api/v1/files", headers=headers, files=_post_data(purpose))
            assert uploaded.status_code == 201
            documents[purpose] = uploaded.json()["file_id"]
        created = client.post(
            "/api/v1/me/verification-requests",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={
                "passport": {
                    "full_name": "Test Applicant",
                    "birth_date": "1990-01-01",
                    "passport_number": "1234 567890",
                    "issued_by": "Test authority",
                },
                "documents": documents,
            },
        )
        assert created.status_code == 201, created.text
        orphan = client.post(
            "/api/v1/files", headers=headers, files=_post_data("verification_passport")
        )
        assert orphan.status_code == 201

    async def age_files() -> None:
        engine = create_engine(dsn)
        try:
            async with create_session_factory(engine).begin() as session:
                configure_session(
                    session, tenant_id=seeded.tenant_a, database_role="keep_rollin_app"
                )
                await session.execute(
                    update(FileRecord).values(created_at=datetime.now(UTC) - timedelta(days=2))
                )
        finally:
            await engine.dispose()

    asyncio.run(age_files())
    assert cli.main(["purge-orphan-uploads"]) == 0
    assert "dry-run: 1 orphan uploads" in capsys.readouterr().out
    assert cli.main(["purge-orphan-uploads", "--execute"]) == 0
    assert "purged 1 orphan uploads" in capsys.readouterr().out
    assert set(storage.objects) == {
        (False, f"{seeded.tenant_a}/{file_id}.jpg") for file_id in documents.values()
    }
