from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant
from src.application.services.outbox import (
    NoopOutboxHandler,
    OutboxConsumer,
    OutboxProcessResult,
    OutboxWriter,
)
from src.domain.entities.outbox_message import DuplicateOutboxEventError
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.repositories.outbox_repository import OutboxRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)

NOW = datetime(2026, 1, 1, 10, tzinfo=UTC)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest_asyncio.fixture
async def seeded(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID]]:
    suffix = uuid4().hex[:10]
    tenant_a = Tenant(
        id=uuid4(),
        name="Outbox A",
        slug=f"outbox-a-{suffix}",
        domain=f"outbox-a-{suffix}.test",
        subdomain=f"outbox-a-{suffix}",
    )
    tenant_b = Tenant(
        id=uuid4(),
        name="Outbox B",
        slug=f"outbox-b-{suffix}",
        domain=f"outbox-b-{suffix}.test",
        subdomain=f"outbox-b-{suffix}",
    )
    async with session_factory() as session:
        session.add_all([tenant_a, tenant_b])
        await session.commit()
    try:
        yield tenant_a.id, tenant_b.id
    finally:
        async with session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant_a.id, tenant_b.id])))
            await session.commit()


def _configured(session: AsyncSession, tenant_id: UUID) -> None:
    configure_session(session, tenant_id=tenant_id, database_role="keep_rollin_app")


async def test_writer_enqueues_and_duplicate_chain_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID],
) -> None:
    tenant_a, _tenant_b = seeded
    entity_id = uuid4()
    async with session_factory() as session:
        _configured(session, tenant_a)
        writer = OutboxWriter(OutboxRepository(session))
        await writer.enqueue(
            event_type="booking.confirmed",
            entity_id=entity_id,
            channel="email",
            payload={"rental_id": "one"},
            now=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        _configured(session, tenant_a)
        writer = OutboxWriter(OutboxRepository(session))
        with pytest.raises(DuplicateOutboxEventError):
            await writer.enqueue(
                event_type="booking.confirmed",
                entity_id=entity_id,
                channel="email",
                payload={"rental_id": "two"},
                now=NOW,
            )
        await session.rollback()


async def test_claim_uses_skip_locked_and_is_tenant_scoped(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = seeded
    async with session_factory() as session:
        _configured(session, tenant_a)
        await OutboxWriter(OutboxRepository(session)).enqueue(
            event_type="event",
            now=NOW,
        )
        await session.commit()

    async with session_factory() as first:
        _configured(first, tenant_a)
        claimed = await OutboxRepository(first).claim_due(now=NOW, limit=10)
        assert len(claimed) == 1

        async with session_factory() as second:
            _configured(second, tenant_a)
            assert await OutboxRepository(second).claim_due(now=NOW, limit=10) == []
            await second.rollback()
        await first.rollback()

    async with session_factory() as other:
        _configured(other, tenant_b)
        assert await OutboxRepository(other).claim_due(now=NOW, limit=10) == []
        await other.rollback()


async def test_consumer_retries_then_fails(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID],
) -> None:
    tenant_a, _tenant_b = seeded

    class FailingHandler:
        async def handle(self, message: object) -> None:
            raise RuntimeError("provider down")

    async def enqueue() -> None:
        async with session_factory() as session:
            _configured(session, tenant_a)
            await OutboxWriter(OutboxRepository(session)).enqueue(event_type="event", now=NOW)
            await session.commit()

    async def process(at: datetime) -> OutboxProcessResult:
        async with session_factory() as session:
            _configured(session, tenant_a)
            result = await OutboxConsumer(OutboxRepository(session)).process_once(
                FailingHandler(), now=at
            )
            await session.commit()
            return result

    await enqueue()
    first = await process(NOW)
    assert first.retried == 1
    second = await process(NOW)
    assert second.claimed == 0
    third = await process(NOW + timedelta(minutes=1))
    assert third.retried == 1
    fourth = await process(NOW + timedelta(minutes=6))
    assert fourth.retried == 1
    fifth = await process(NOW + timedelta(minutes=21))
    assert fifth.failed == 1

    async with session_factory() as session:
        _configured(session, tenant_a)
        record = (await session.execute(select(OutboxMessageRecord))).scalar_one()
        assert record.status == "failed"
        assert record.attempts == 4
        assert record.last_error == "provider down"


async def test_noop_handler_marks_processed(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: tuple[UUID, UUID],
) -> None:
    tenant_a, _tenant_b = seeded
    async with session_factory() as session:
        _configured(session, tenant_a)
        await OutboxWriter(OutboxRepository(session)).enqueue(event_type="event", now=NOW)
        await session.commit()

    async with session_factory() as session:
        _configured(session, tenant_a)
        result = await OutboxConsumer(OutboxRepository(session)).process_once(
            NoopOutboxHandler(), now=NOW
        )
        await session.commit()

    assert result.processed == 1
    async with session_factory() as session:
        _configured(session, tenant_a)
        record = (await session.execute(select(OutboxMessageRecord))).scalar_one()
        assert record.status == "processed"
        assert record.processed_at is not None
