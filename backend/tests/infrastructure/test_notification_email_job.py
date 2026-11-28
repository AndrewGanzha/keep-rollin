import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from prometheus_client import generate_latest
from pydantic import SecretStr, ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql.ranges import Range
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from app.models import Tenant, User
from app.notification_email_job import SmtpSettings, create_email_job
from app.worker import Worker, WorkerSettings, worker_session
from src.infrastructure.email import EMAIL_EVENT_TYPES, RenderedEmail, SmtpEmailSender
from src.infrastructure.email.smtp import SmtpDeliveryError
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.password_reset_token_record import PasswordResetTokenRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.security.password_hasher import Argon2PasswordHasher
from src.infrastructure.security.secret_box import SecretBox

DATABASE_URL = os.getenv("DATABASE_URL")
SMTP_PORT = os.getenv("MAILHOG_SMTP_PORT")
MAILHOG_URL = os.getenv("MAILHOG_HTTP_URL")
requires_postgres = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL is required")
NOW = datetime(2026, 11, 28, tzinfo=UTC)
RESET_EVENT = "auth.password_reset"
RESET_KEY = "test-only-keep-rollin-previous-key-123456789"
CURRENT_RESET_KEY = "test-only-keep-rollin-current-key-123456789"


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
        security_key=None,
        security_key_id="primary",
        security_previous_keys={},
    )


async def dispatch(
    engine: AsyncEngine, tenant: UUID, now: datetime = NOW, *, smtp: SmtpSettings | None = None
) -> int:
    job = create_email_job(smtp or settings())
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
    monkeypatch.delenv("SECURITY_KEY", raising=False)
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
        reset = message(tenant, default, RESET_EVENT, channel="email")
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
async def test_password_reset_mail_skips_unusable_rows(
    database: tuple[AsyncEngine, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, other = database
    sessions = create_session_factory(engine)
    now = datetime.now(UTC)
    secret_box = SecretBox.from_settings(RESET_KEY)
    async with sessions.begin() as session:
        active = await seed(session, tenant)
        inactive = await seed(session, tenant, active=False)
        other_tenant_user = await seed(session, other)
        invalid_recipient = await seed(session, tenant)
        user = await session.get_one(User, invalid_recipient)
        user.email = "legacy@example..test"

        records, events = [], []
        for row_tenant, row_user, event_user, expiry, consumed in (
            (tenant, active, active, now - timedelta(seconds=1), None),
            (tenant, active, active, now + timedelta(hours=1), now),
            (tenant, inactive, inactive, now + timedelta(hours=1), None),
            (tenant, inactive, active, now + timedelta(hours=1), None),
            (other, other_tenant_user, active, now + timedelta(hours=1), None),
            (tenant, invalid_recipient, invalid_recipient, now + timedelta(hours=1), None),
        ):
            row_id = uuid4()
            records.append(
                PasswordResetTokenRecord(
                    id=row_id,
                    tenant_id=row_tenant,
                    user_id=row_user,
                    token_hash=row_id.hex,
                    token_secret_enc=secret_box.encrypt(
                        "d" * 43, context=f"reset:{row_tenant}:{row_user}"
                    ),
                    expires_at=expiry,
                    consumed_at=consumed,
                )
            )
            event = message(tenant, event_user, RESET_EVENT, channel="email", available_at=now)
            event.entity_id = row_id
            events.append(event)
        events.append(message(tenant, active, RESET_EVENT, channel="email", available_at=now))
        session.add_all(records)
        session.add_all(events)

    async with (
        engine.connect() as connection,
        worker_session(connection, tenant) as session,
        session.begin(),
    ):
        assert (
            await session.scalar(
                select(PasswordResetTokenRecord.id).where(
                    PasswordResetTokenRecord.id == records[4].id
                )
            )
            is None
        )
        assert not await session.scalar(
            text("SELECT has_column_privilege('password_reset_token', 'token_hash', 'SELECT')")
        )

    def unexpected_message(self: SmtpEmailSender, email: EmailMessage) -> None:
        pytest.fail("An unusable password reset generated SMTP traffic")

    monkeypatch.setattr(SmtpEmailSender, "_send_message", unexpected_message)
    smtp = settings().model_copy(update={"security_key": SecretStr(RESET_KEY)})
    for _ in events:
        assert await dispatch(engine, tenant, now, smtp=smtp) == 1
    assert await dispatch(engine, tenant, now, smtp=smtp) == 0
    async with sessions() as session:
        for event in events:
            saved = await session.get_one(OutboxMessageRecord, event.id)
            assert (saved.status, saved.attempts, saved.last_error) == ("processed", 0, None)


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
        category, lot, occupancy = uuid4(), uuid4(), uuid4()
        session.add(CategoryRecord(id=category, tenant_id=tenant, name="Demo", slug="demo"))
        await session.flush()
        session.add(
            LotRecord(
                id=lot,
                tenant_id=tenant,
                category_id=category,
                slug="demo",
                name="Demo",
                rental_unit="hour",
                allowed_durations=[1],
                status="active",
            )
        )
        await session.flush()
        reminder = events["rental.ending_soon"]
        assert reminder.entity_id is not None
        start = datetime.now(UTC) - timedelta(minutes=40)
        end = start + timedelta(hours=1)
        session.add(
            OccupancyRecord(
                id=occupancy,
                tenant_id=tenant,
                lot_id=lot,
                kind="booking",
                period=Range(start, end, bounds="[)"),
                ref_id=reminder.entity_id,
            )
        )
        session.add(
            RentalRecord(
                id=reminder.entity_id,
                tenant_id=tenant,
                user_id=user_id,
                lot_id=lot,
                occupancy_id=occupancy,
                variant_id=uuid4(),
                battery_count=0,
                status="active",
                start_time=start,
                end_time=end,
                price_minor=100,
                currency="RUB",
                cancellation_deadline=start - timedelta(hours=24),
            )
        )
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
            "verification.approved": "/account/verification",
            "verification.rejected": "/account/verification",
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


@requires_postgres
@pytest.mark.skipif(not (SMTP_PORT and MAILHOG_URL), reason="A disposable MailHog is required")
async def test_password_reset_request_is_delivered_by_worker_and_can_only_be_used_once(
    database: tuple[AsyncEngine, UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DATABASE_URL and SMTP_PORT and MAILHOG_URL
    engine, tenant, _ = database
    sessions = create_session_factory(engine)
    domain = f"notification-{tenant.hex[:14]}.test"
    origin = f"https://{domain}"
    async with sessions.begin() as session:
        user_id = await seed(session, tenant, email_allowed=False)
        user = await session.get_one(User, user_id)
        user.password_hash = Argon2PasswordHasher().hash("Old-Cycling-Password-2026")
        user.notification_preferences = {
            "push_enabled": False,
            "email_by_event": {RESET_EVENT: False},
        }
        address = user.email

    api = create_app(
        Settings(app_env="test", security_key=RESET_KEY, security_key_id="prior"),
        session_factory=sessions,
    )
    # The API encrypted the queued token before the worker's key was rotated.
    monkeypatch.setenv("SECURITY_KEY", CURRENT_RESET_KEY)
    monkeypatch.setenv("SECURITY_KEY_ID", "current")
    monkeypatch.setenv("SECURITY_PREVIOUS_KEYS", json.dumps({"prior": RESET_KEY}))
    worker = Worker(
        engine,
        WorkerSettings(
            database_url=SecretStr(DATABASE_URL),
            smtp=SmtpSettings(
                host="127.0.0.1",
                from_address="notifications@example.test",
                port=int(SMTP_PORT),
                security="plain",
            ),
        ),
    )
    try:
        async with (
            api.router.lifespan_context(api),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api),
                base_url=origin,
                headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"},
            ) as client,
        ):
            request = await client.post("/api/v1/auth/password/forgot", json={"email": address})
            unknown = await client.post(
                "/api/v1/auth/password/forgot", json={"email": "unknown@example.test"}
            )
            assert request.status_code == unknown.status_code == 202
            assert request.json() == unknown.json()
            async with sessions() as session:
                event = (
                    await session.scalars(
                        select(OutboxMessageRecord).where(
                            OutboxMessageRecord.tenant_id == tenant,
                            OutboxMessageRecord.event_type == RESET_EVENT,
                        )
                    )
                ).one()
                assert event.status == "pending"
                assert event.payload == {"reset_token_id": str(event.entity_id)}

            await worker.run("email_delivery", worker.jobs["email_delivery"])
            await worker.run("email_delivery", worker.jobs["email_delivery"])
            async with sessions() as session:
                saved = await session.get_one(OutboxMessageRecord, event.id)
                assert (saved.status, saved.attempts, saved.last_error) == ("processed", 0, None)

            async with httpx.AsyncClient(base_url=MAILHOG_URL) as mailbox:
                response = await mailbox.get("/api/v2/messages")
                response.raise_for_status()
            parser = BytesParser(policy=policy.default)
            emails = [
                mime
                for item in response.json()["items"]
                if (mime := parser.parsebytes(item["Raw"]["Data"].encode()))
                and str(mime["To"]) == address
            ]
            assert len(emails) == 1
            mime = emails[0]
            assert str(mime["Message-ID"]) == f"<{event.id}@example.test>"
            assert mime.get_content_type() == "multipart/alternative"
            body = mime.get_body(preferencelist=("plain",))
            html = mime.get_body(preferencelist=("html",))
            assert body is not None and html is not None
            link = body.get_content().strip().splitlines()[-1]
            location = urlsplit(link)
            assert (location.scheme, location.netloc, location.path, location.query) == (
                "https",
                domain,
                "/password/reset",
                "",
            )
            assert f'href="{link}"' in html.get_content()
            token = parse_qs(location.fragment)["token"][0]
            submission = {"token": token, "password": "New-Cycling-Password-2026"}
            reset = await client.post("/api/v1/auth/password/reset", json=submission)
            assert reset.status_code == 204
            assert "set-cookie" not in reset.headers
            repeated = await client.post("/api/v1/auth/password/reset", json=submission)
            assert repeated.status_code == 401
    finally:
        await worker.close()
