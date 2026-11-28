import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import create_engine, create_session_factory
from app.models import Tenant, User
from app.notification_email_job import SmtpSettings, create_email_job
from app.notification_push_job import PushSettings, create_push_jobs
from app.worker import worker_session
from app.worker_jobs import Job
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.push_subscription_record import PushSubscriptionRecord
from src.infrastructure.postgres.models.tenant_settings_record import TenantSettingsRecord
from src.infrastructure.push.sender import PushSendKind, PushSendResult, WebPushSender
from src.infrastructure.security.secret_box import SecretBox
from src.infrastructure.security.vapid import generate_vapid_keypair

DATABASE_URL = os.getenv("DATABASE_URL")
POSTGRES = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL is required")
NOW = datetime(2026, 11, 28, 14, tzinfo=UTC)
TEST_SECURITY_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"


@dataclass(frozen=True)
class DeliveryDb:
    engine: AsyncEngine
    tenant: UUID
    user: UUID
    other: UUID
    other_user: UUID
    private_key: str


@pytest.fixture
async def delivery_db() -> AsyncIterator[DeliveryDb]:
    assert DATABASE_URL
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    tenant, user, other, other_user = (uuid4() for _ in range(4))
    keys = generate_vapid_keypair()
    try:
        async with sessions.begin() as session:
            for tenant_id, user_id in ((tenant, user), (other, other_user)):
                label = f"web-push-{tenant_id.hex[:16]}"
                session.add(Tenant(id=tenant_id, slug=label, domain=f"{label}.test", name=label))
                await session.flush()
                session.add(
                    User(
                        id=user_id,
                        tenant_id=tenant_id,
                        email=f"{user_id.hex}@example.test",
                        name=label,
                    )
                )
                session.add(
                    TenantSettingsRecord(
                        tenant_id=tenant_id,
                        vapid_public_key=keys.public_key,
                        vapid_private_key_enc=SecretBox.from_settings(TEST_SECURITY_KEY).encrypt(
                            keys.private_key, context=f"vapid:{tenant_id}"
                        ),
                    )
                )
        yield DeliveryDb(engine, tenant, user, other, other_user, keys.private_key)
    finally:
        async with sessions.begin() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant, other])))
        await engine.dispose()


def push_jobs() -> dict[str, Job]:
    return create_push_jobs(
        PushSettings.model_validate(
            {
                "enabled": True,
                "subject": "mailto:delivery@example.test",
                "SECURITY_KEY": TEST_SECURITY_KEY,
            }
        )
    )


async def run(db: DeliveryDb, job: Job, now: datetime = NOW) -> int:
    async with (
        db.engine.connect() as connection,
        worker_session(connection, db.tenant) as session,
        session.begin(),
    ):
        return await job(session, now, 100, "trace")


def event(
    db: DeliveryDb,
    *,
    event_type: str,
    user: UUID | None = None,
    channel: str | None = None,
    attempts: int = 0,
) -> OutboxMessageRecord:
    return OutboxMessageRecord(
        id=uuid4(),
        tenant_id=db.tenant,
        user_id=user or db.user,
        entity_id=uuid4(),
        channel=channel,
        event_type=event_type,
        available_at=NOW,
        attempts=attempts,
    )


def subscription(db: DeliveryDb, tag: str, *, foreign: bool = False) -> PushSubscriptionRecord:
    return PushSubscriptionRecord(
        id=uuid4(),
        tenant_id=db.other if foreign else db.tenant,
        user_id=db.other_user if foreign else db.user,
        endpoint=f"https://fcm.googleapis.com/fcm/send/{tag}",
        version=uuid4(),
        p256dh=generate_vapid_keypair().public_key,
        auth="AAECAwQFBgcICQoLDA0ODw",
        created_at=NOW + timedelta(seconds=len(tag)),
    )


def test_push_jobs_are_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKER_PUSH_ENABLED", raising=False)
    monkeypatch.delenv("WORKER_PUSH_SUBJECT", raising=False)
    monkeypatch.delenv("SECURITY_KEY", raising=False)
    assert create_push_jobs(PushSettings(_env_file=None)) == {}
    with pytest.raises(ValidationError, match="WORKER_PUSH_SUBJECT"):
        PushSettings(enabled=True, _env_file=None)
    with pytest.raises(ValidationError, match="mailto or HTTPS"):
        PushSettings.model_validate(
            {
                "enabled": True,
                "subject": "wrong-contact",
                "SECURITY_KEY": TEST_SECURITY_KEY,
            }
        )


@pytest.mark.parametrize(
    ("critical", "push_on", "email_on", "devices", "channels", "attempted", "terminal"),
    [
        (False, True, True, (), {"push", "email"}, [], None),
        (False, True, False, (), {"push"}, [], None),
        (False, False, True, ("accepted",), {"email"}, [], None),
        (False, False, False, ("accepted",), set(), [], None),
        (False, True, True, ("accepted",), {"push"}, ["accepted"], None),
        (False, True, True, ("gone", "accepted"), {"push"}, ["gone", "accepted"], None),
        (False, True, True, ("gone",), {"push", "email"}, ["gone"], None),
        (False, True, True, ("permanent",), {"push", "email"}, ["permanent"], "failed"),
        (True, False, False, ("accepted",), {"push", "email"}, ["accepted"], None),
        (True, False, False, ("permanent",), {"push", "email"}, ["permanent"], "failed"),
    ],
)
@POSTGRES
async def test_routes_channels_by_recipient_preferences_and_provider_result(
    delivery_db: DeliveryDb,
    monkeypatch: pytest.MonkeyPatch,
    critical: bool,
    push_on: bool,
    email_on: bool,
    devices: tuple[str, ...],
    channels: set[str],
    attempted: list[str],
    terminal: str | None,
) -> None:
    db = delivery_db
    sessions = create_session_factory(db.engine)
    event_type = "rental.overdue.user" if critical else "booking.confirmed"
    original = event(db, event_type=event_type)
    subs = [subscription(db, name) for name in devices]
    foreign = subscription(db, "foreign", foreign=True)
    async with sessions.begin() as session:
        user = await session.get_one(User, db.user)
        user.notification_preferences = {
            "push_enabled": push_on,
            "email_by_event": {event_type: email_on},
        }
        session.add_all([original, foreign, *subs])

    sent = []

    async def send(
        self: WebPushSender,
        *,
        endpoint: str,
        p256dh: str,
        auth: str,
        vapid_private_key: str,
        payload: str,
        ttl: int,
    ) -> PushSendResult:
        assert vapid_private_key == db.private_key
        assert ttl == 300
        data = json.loads(payload)
        assert data["url"] == "/account/rentals"
        assert len(data["tag"]) == 36
        suffix = endpoint.rsplit("/", 1)[-1]
        sent.append(suffix)
        return PushSendResult(PushSendKind(suffix))

    monkeypatch.setattr(WebPushSender, "send", send)
    jobs = push_jobs()
    assert await run(db, jobs["notification_routing"]) == 1
    assert await run(db, jobs["notification_routing"]) == 0
    if critical:
        async with sessions() as session:
            queued = (
                await session.scalars(
                    select(OutboxMessageRecord).where(
                        OutboxMessageRecord.entity_id == original.entity_id,
                        OutboxMessageRecord.channel == "email",
                    )
                )
            ).one()
            assert queued.status == "pending"
    assert await run(db, jobs["push_delivery"]) == int("push" in channels)
    assert await run(db, jobs["push_delivery"]) == 0
    assert sent == attempted

    async with sessions() as session:
        rows = (
            await session.scalars(
                select(OutboxMessageRecord).where(
                    OutboxMessageRecord.entity_id == original.entity_id
                )
            )
        ).all()
        assert {row.channel for row in rows if row.channel} == channels
        state = {row.channel: row.status for row in rows}
        assert state[None] == "processed"
        if "push" in channels:
            assert state["push"] == (terminal or "processed")
        for record in [foreign, *subs]:
            saved = await session.get_one(PushSubscriptionRecord, record.id)
            assert (saved.disabled_at is not None) == record.endpoint.endswith("/gone")


@POSTGRES
async def test_retry_exhaustion_and_existing_smtp_chains(
    delivery_db: DeliveryDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = delivery_db
    sessions = create_session_factory(db.engine)
    message = event(db, event_type="booking.confirmed")
    existing = event(db, event_type="booking.confirmed", attempts=1)
    reset = event(db, event_type="auth.password_reset", channel="email")
    wrong_tenant = event(db, event_type="booking.confirmed", user=db.other_user)
    row = subscription(db, "retryable")
    async with sessions.begin() as session:
        session.add_all([message, existing, reset, wrong_tenant, row])

    async def send(self: WebPushSender, **kwargs: object) -> PushSendResult:
        return PushSendResult(PushSendKind.RETRYABLE)

    monkeypatch.setattr(WebPushSender, "send", send)
    jobs = push_jobs()
    assert await run(db, jobs["notification_routing"]) == 2
    for delay in (0, 1, 6, 21):
        instant = NOW + timedelta(minutes=delay)
        assert await run(db, jobs["push_delivery"], instant) == 1
        assert await run(db, jobs["push_delivery"], instant) == 0

    async with sessions() as session:
        actual = (
            await session.scalars(
                select(OutboxMessageRecord).where(
                    OutboxMessageRecord.entity_id == message.entity_id
                )
            )
        ).all()
        children = {value.channel: value for value in actual}
        assert children["email"].status == "pending"
        assert (
            children["push"].status,
            children["push"].attempts,
            children["push"].last_error,
        ) == (
            "failed",
            4,
            "web_push_retryable",
        )
        assert (await session.get_one(OutboxMessageRecord, existing.id)).attempts == 1
        assert (await session.get_one(OutboxMessageRecord, reset.id)).status == "pending"
    smtp = create_email_job(
        SmtpSettings(
            host="127.0.0.1",
            from_address="notifications@example.test",
            security="plain",
        ),
        push_routing_enabled=True,
    )
    assert smtp is not None

    # Prove the legacy SMTP row is still claimable while the new router is active.
    async def fake_mail(self: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("src.infrastructure.email.smtp.SmtpEmailSender.send", fake_mail)
    assert await run(db, smtp) == 1
    assert await run(db, smtp) == 0
    async with sessions() as session:
        assert (await session.get_one(OutboxMessageRecord, existing.id)).status == "processed"


@POSTGRES
async def test_critical_email_is_not_resent_during_push_retries(
    delivery_db: DeliveryDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = delivery_db
    sessions = create_session_factory(db.engine)
    original = event(db, event_type="rental.overdue.user")
    async with sessions.begin() as session:
        session.add_all([original, subscription(db, "retryable")])

    async def push(self: WebPushSender, **kwargs: object) -> PushSendResult:
        return PushSendResult(PushSendKind.RETRYABLE)

    emails: list[UUID] = []

    async def smtp(self: object, *, recipient: str, email: object, message_id: UUID) -> None:
        emails.append(message_id)

    monkeypatch.setattr(WebPushSender, "send", push)
    monkeypatch.setattr("src.infrastructure.email.smtp.SmtpEmailSender.send", smtp)
    jobs = push_jobs()
    email_job = create_email_job(
        SmtpSettings(host="127.0.0.1", from_address="notifications@example.test", security="plain"),
        push_routing_enabled=True,
    )
    assert email_job is not None

    # Routed and delivered independently before the push provider is called.
    assert await run(db, jobs["notification_routing"]) == 1
    assert await run(db, email_job) == 1
    for delay in (0, 1, 6, 21):
        now = NOW + timedelta(minutes=delay)
        assert await run(db, jobs["push_delivery"], now) == 1
        assert await run(db, email_job, now) == 0
    assert len(emails) == 1
