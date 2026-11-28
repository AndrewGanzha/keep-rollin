import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from uuid import UUID, uuid4

import httpx
import pytest
from prometheus_client import generate_latest
from pydantic import SecretStr, ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db import create_engine, create_session_factory
from app.models import Tenant, User
from app.notification_email_job import SmtpSettings, create_email_job
from app.worker import Worker, WorkerSettings, worker_session
from src.infrastructure.email import EMAIL_EVENT_TYPES, RenderedEmail, SmtpEmailSender
from src.infrastructure.email.smtp import SmtpDeliveryError
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord

DATABASE_URL = os.getenv("DATABASE_URL")
SMTP_PORT = os.getenv("MAILHOG_SMTP_PORT")
MAILHOG_URL = os.getenv("MAILHOG_HTTP_URL")
requires_postgres = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL is required")
NOW = datetime(2026, 11, 28, tzinfo=UTC)


@pytest.fixture
async def database() -> AsyncIterator[tuple[AsyncEngine, UUID, UUID]]:
    assert DATABASE_URL
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    tenant, other = uuid4(), uuid4()
    try:
        async with sessions.begin() as session:
            for tenant_id in (tenant, other):
                name = f"notification-{tenant_id.hex[:14]}"
                session.add(Tenant(id=tenant_id, slug=name, name=name, domain=f"{name}.test"))
        yield engine, tenant, other
    finally:
        async with sessions.begin() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant, other])))
        await engine.dispose()


async def seed(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    active: bool = True,
    role: str = "user",
    email_allowed: bool = True,
) -> UUID:
    user_id = uuid4()
    session.add(
        User(
            id=user_id,
            tenant_id=tenant_id,
            name="Recipient",
            email=f"{user_id.hex}@example.test",
            is_active=active,
            role=role,
            notification_preferences={
                "email_by_event": {"booking.confirmed": email_allowed},
            },
        )
    )
    await session.flush()
    return user_id


def message(
    tenant_id: UUID,
    user_id: UUID,
    event_type: str = "booking.confirmed",
    *,
    channel: str | None = None,
    available_at: datetime = NOW,
) -> OutboxMessageRecord:
    return OutboxMessageRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        entity_id=uuid4(),
        user_id=user_id,
        event_type=event_type,
        channel=channel,
        available_at=available_at,
    )


def settings(*, port: int = 1025) -> SmtpSettings:
    return SmtpSettings(
        host="127.0.0.1",
        from_address="notifications@example.test",
        port=port,
        security="plain",
    )


async def dispatch(engine: AsyncEngine, tenant: UUID, now: datetime = NOW) -> int:
    job = create_email_job(settings())
    assert job is not None
    async with (
        engine.connect() as connection,
        worker_session(connection, tenant) as session,
        session.begin(),
    ):
        return await job(session, now, 100, "test-trace")


def test_smtp_job_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKER_SMTP_HOST", raising=False)
    monkeypatch.delenv("WORKER_SMTP_FROM_ADDRESS", raising=False)
    assert create_email_job(SmtpSettings(_env_file=None)) is None
    with pytest.raises(ValidationError, match="must be set together"):
        SmtpSettings(host="127.0.0.1")
    with pytest.raises(ValidationError, match="requires an SMTP host and TLS"):
        SmtpSettings(
            host="127.0.0.1",
            from_address="notifications@example.test",
            security="plain",
            username="smtp-user",
            password=SecretStr("smtp-secret"),
        )


@requires_postgres
async def test_email_dispatch_respects_scope_channels_and_preferences(
    database: tuple[AsyncEngine, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, other = database
    sessions = create_session_factory(engine)
    async with sessions.begin() as session:
        default = await seed(session, tenant)
        opted_out = await seed(session, tenant, email_allowed=False)
        inactive = await seed(session, tenant, active=False)
        foreign = await seed(session, other)
        enabled = message(tenant, default)
        disabled = message(tenant, opted_out)
        mandatory = message(tenant, opted_out, "rental.overdue.user", channel="email")
        inactive_event = message(tenant, inactive)
        wrong_tenant_recipient = message(tenant, foreign)
        foreign_event = message(other, foreign)
        push = message(tenant, default, channel="push")
        reset = message(tenant, default, "auth.password_reset", channel="email")
        unknown = message(tenant, default, "future.event")
        session.add_all(
            [
                enabled,
                disabled,
                mandatory,
                inactive_event,
                wrong_tenant_recipient,
                foreign_event,
                push,
                reset,
                unknown,
            ]
        )

    sent: dict[UUID, tuple[str, RenderedEmail]] = {}

    async def send(
        self: SmtpEmailSender, *, recipient: str, email: RenderedEmail, message_id: UUID
    ) -> None:
        assert message_id not in sent
        sent[message_id] = (recipient, email)

    monkeypatch.setattr(SmtpEmailSender, "send", send)
    for _ in range(5):
        assert await dispatch(engine, tenant) == 1
    assert await dispatch(engine, tenant) == 0
    assert set(sent) == {enabled.id, mandatory.id}
    assert sent[enabled.id][0] == f"{default.hex}@example.test"
    assert sent[mandatory.id][0] == f"{opted_out.hex}@example.test"
    async with sessions() as session:
        for item in (enabled, disabled, mandatory, inactive_event, wrong_tenant_recipient):
            saved = await session.get_one(OutboxMessageRecord, item.id)
            assert (saved.status, saved.processed_at, saved.last_error) == ("processed", NOW, None)
        for item in (foreign_event, push, reset, unknown):
            saved = await session.get_one(OutboxMessageRecord, item.id)
            assert (saved.status, saved.attempts) == ("pending", 0)


@requires_postgres
async def test_email_dispatch_retries_with_same_message_id_and_no_server_text(
    database: tuple[AsyncEngine, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = database
    sessions = create_session_factory(engine)
    async with sessions.begin() as session:
        user_id = await seed(session, tenant)
        event = message(tenant, user_id)
        session.add(event)
    attempted: list[UUID] = []

    async def reject(
        self: SmtpEmailSender, *, recipient: str, email: RenderedEmail, message_id: UUID
    ) -> None:
        attempted.append(message_id)
        raise SmtpDeliveryError("server response with recipient@example.test")

    monkeypatch.setattr(SmtpEmailSender, "send", reject)
    for delay in (0, 1, 6, 21):
        assert await dispatch(engine, tenant, NOW + timedelta(minutes=delay)) == 1
        assert await dispatch(engine, tenant, NOW + timedelta(minutes=delay)) == 0
    assert attempted == [event.id] * 4
    async with sessions() as session:
        saved = await session.get_one(OutboxMessageRecord, event.id)
        assert (saved.status, saved.attempts, saved.last_error) == (
            "failed",
            4,
            "smtp_delivery_failed",
        )


@requires_postgres
async def test_invalid_recipient_does_not_block_next_email(
    database: tuple[AsyncEngine, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = database
    sessions = create_session_factory(engine)
    async with sessions.begin() as session:
        bad_id = await seed(session, tenant)
        bad = await session.get_one(User, bad_id)
        bad.email = "legacy@example..test"
        valid_id = await seed(session, tenant)
        blocked = message(tenant, bad_id, available_at=NOW - timedelta(seconds=1))
        valid = message(tenant, valid_id)
        session.add_all((blocked, valid))

    accepted = []

    def send_message(self: SmtpEmailSender, email: EmailMessage) -> None:
        accepted.append(str(email["To"]))

    monkeypatch.setattr(SmtpEmailSender, "_send_message", send_message)
    assert await dispatch(engine, tenant) == 1
    assert await dispatch(engine, tenant) == 1
    assert accepted == [f"{valid_id.hex}@example.test"]
    async with sessions() as session:
        invalid = await session.get_one(OutboxMessageRecord, blocked.id)
        assert (invalid.status, invalid.attempts, invalid.last_error) == (
            "pending",
            1,
            "invalid_email_data",
        )
        delivered = await session.get_one(OutboxMessageRecord, valid.id)
        assert delivered.status == "processed"


@requires_postgres
@pytest.mark.skipif(not (SMTP_PORT and MAILHOG_URL), reason="A disposable MailHog is required")
async def test_worker_delivers_multipart_message_to_mailhog(
    database: tuple[AsyncEngine, UUID, UUID],
) -> None:
    assert DATABASE_URL and SMTP_PORT and MAILHOG_URL
    engine, tenant, _ = database
    sessions = create_session_factory(engine)
    async with sessions.begin() as session:
        user_id = await seed(session, tenant, role="admin")
        events = {
            event_type: message(tenant, user_id, event_type, available_at=datetime.now(UTC))
            for event_type in EMAIL_EVENT_TYPES
        }
        session.add_all(events.values())
    worker = Worker(
        engine,
        WorkerSettings(
            database_url=SecretStr(DATABASE_URL),
            smtp=settings(port=int(SMTP_PORT)),
        ),
    )
    try:
        await worker.run("email_delivery", worker.jobs["email_delivery"])
        async with sessions() as session:
            for event in events.values():
                saved = await session.get_one(OutboxMessageRecord, event.id)
                assert saved.status == "processed"
        metrics = generate_latest(worker.registry)
        assert b'worker_email_delivery_attempts_total{outcome="sent"} 11.0' in metrics
        async with httpx.AsyncClient(base_url=MAILHOG_URL) as client:
            response = await client.get("/api/v2/messages")
            response.raise_for_status()
            items = response.json()["items"]
        parser = BytesParser(policy=policy.default)
        by_id = {
            str(mime["Message-ID"]): mime
            for item in items
            if (mime := parser.parsebytes(item["Raw"]["Data"].encode()))
            and str(mime["To"]) == f"{user_id.hex}@example.test"
        }
        assert len(by_id) == len(events) == 11
        paths = {
            "rental.overdue.admin": "/admin/rentals",
            "ticket.created.admin": "/admin/tickets",
            "ticket.updated.user": "/account/tickets",
            "ticket.resolved.user": "/account/tickets",
        }
        for event_type, event in events.items():
            mime = by_id[f"<{event.id}@example.test>"]
            assert mime.get_content_type() == "multipart/alternative"
            link = f"https://notification-{tenant.hex[:14]}.test"
            link += paths.get(event_type, "/account/rentals")
            for kind in ("plain", "html"):
                part = mime.get_body(preferencelist=(kind,))
                assert part is not None
                assert link in part.get_content()
    finally:
        await worker.close()
