import asyncio
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from pydantic import SecretStr, ValidationError
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db import create_engine
from app.models import Tenant, User
from app.worker import Worker, WorkerSettings, create_app, job_connection, worker_session
from src.infrastructure.postgres.models.idempotency_key_record import IdempotencyKeyRecord

DATABASE_URL = os.getenv("DATABASE_URL")
requires_database = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL is required")


def settings() -> WorkerSettings:
    assert DATABASE_URL is not None
    return WorkerSettings(database_url=SecretStr(DATABASE_URL), interval_seconds=3600)


@pytest.fixture
async def database() -> AsyncIterator[tuple[AsyncEngine, UUID, UUID]]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    active, inactive = uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(Tenant),
                [
                    {
                        "id": tenant,
                        "name": tenant.hex,
                        "slug": tenant.hex,
                        "domain": f"{tenant.hex}.test",
                        "is_active": enabled,
                    }
                    for tenant, enabled in [(active, True), (inactive, False)]
                ],
            )
            for tenant in (active, inactive):
                user = uuid4()
                await connection.execute(
                    insert(User).values(
                        id=user, tenant_id=tenant, name="Tester", email=f"{user.hex}@example.test"
                    )
                )
                await connection.execute(
                    insert(IdempotencyKeyRecord).values(
                        tenant_id=tenant,
                        user_id=user,
                        key=uuid4(),
                        request_hash="a" * 64,
                        expires_at=datetime.now(UTC) - timedelta(hours=1),
                    )
                )
        yield engine, active, inactive
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(Tenant).where(Tenant.id.in_([active, inactive])))
        await engine.dispose()


def test_worker_requires_dedicated_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKER_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    with pytest.raises(ValidationError, match="database_url"):
        WorkerSettings(_env_file=None)


@requires_database
async def test_worker_lock_spans_transactions(database: tuple[AsyncEngine, UUID, UUID]) -> None:
    engine, active, _ = database
    assert DATABASE_URL is not None
    replica = create_engine(DATABASE_URL)
    try:
        async with job_connection(engine, "test_replica_lock") as first:
            assert first is not None
            async with worker_session(first, active) as session, session.begin():
                assert await session.scalar(text("SELECT current_user")) == "keep_rollin_worker"
                assert await session.scalar(text("SELECT current_setting('app.tenant_id')")) == str(
                    active
                )
            async with job_connection(replica, "test_replica_lock") as second:
                assert second is None
        async with job_connection(replica, "test_replica_lock") as connection:
            assert connection is not None
            assert await connection.scalar(
                text("SELECT current_setting('app.tenant_id', true)")
            ) in (
                None,
                "",
            )
    finally:
        await replica.dispose()


@requires_database
async def test_worker_protects_private_columns(
    database: tuple[AsyncEngine, UUID, UUID], caplog: pytest.LogCaptureFixture
) -> None:
    engine, active, inactive = database
    worker = Worker(engine, settings())
    seen = []

    async def probe(session: AsyncSession, now: datetime, limit: int, trace_id: str) -> int:
        tenant_id = await session.scalar(text("SELECT current_setting('app.tenant_id')"))
        seen.append(tenant_id)
        if tenant_id == str(active):
            visible = (await session.scalars(select(IdempotencyKeyRecord.tenant_id))).all()
            assert list(visible) == [active]
            await session.execute(select(IdempotencyKeyRecord.response))
        return 0

    try:
        with caplog.at_level(logging.ERROR, logger="app.worker"):
            await worker.run("idempotency_expiry", probe)
        assert str(active) in seen and str(inactive) not in seen
        assert len([record for record in caplog.records if record.msg == "worker job failed"]) == 1
        failure = next(record for record in caplog.records if record.msg == "worker tenant failed")
        assert failure.__dict__["trace_id"]
        assert failure.__dict__["error_type"] == "ProgrammingError"
        assert not failure.exc_info
        assert b'worker_job_errors_total{job="idempotency_expiry"} 1.0' in generate_latest(
            worker.registry
        )
    finally:
        await worker.close()


@requires_database
async def test_worker_shutdown_drains_current_batch(
    database: tuple[AsyncEngine, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, active, _ = database
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow(session: AsyncSession, now: datetime, limit: int, trace_id: str) -> int:
        if await session.scalar(text("SELECT current_setting('app.tenant_id')")) != str(active):
            return 0
        await session.execute(delete(IdempotencyKeyRecord))
        entered.set()
        await release.wait()
        return 1

    monkeypatch.setattr("app.worker.JOBS", {"idempotency_expiry": slow})
    worker = Worker(engine, settings())
    worker.start()
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        close = asyncio.create_task(worker.close())
        await asyncio.sleep(0)
        assert not close.done()
        release.set()
        await asyncio.wait_for(close, timeout=5)
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(IdempotencyKeyRecord.key).where(IdempotencyKeyRecord.tenant_id == active)
                )
                is None
            )
    finally:
        release.set()
        if worker.accepting:
            await worker.close()


@requires_database
def test_worker_serves_health_readiness_and_metrics() -> None:
    with TestClient(create_app(settings())) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 200
        response = client.get("/metrics")
        assert response.status_code == 200
        assert 'worker_job_runs_total{job="rental_lifecycle",outcome="success"}' in response.text
        assert "worker_job_duration_seconds_bucket" in response.text
