import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql.ranges import Range
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db import create_engine, create_session_factory
from app.models import Tenant, User
from app.notification_email_job import SmtpSettings, create_email_job
from app.notification_push_job import PushSettings, create_push_jobs
from app.worker import worker_session
from app.worker_jobs import JOBS, Job
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.push_subscription_record import PushSubscriptionRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord, RentalStatus
from src.infrastructure.postgres.models.tenant_settings_record import TenantSettingsRecord
from src.infrastructure.security.secret_box import SecretBox
from src.infrastructure.security.vapid import generate_vapid_keypair

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL is required")
DEMO_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"


@dataclass(frozen=True)
class Site:
    id: UUID
    user: UUID
    category: UUID


@pytest.fixture
async def database() -> AsyncIterator[tuple[AsyncEngine, Site, Site, datetime]]:
    assert DATABASE_URL
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    first = Site(uuid4(), uuid4(), uuid4())
    other = Site(uuid4(), uuid4(), uuid4())
    try:
        async with sessions.begin() as session:
            for site, ahead in ((first, 2), (other, 1)):
                slug = f"reminders-{site.id.hex[:12]}"
                session.add(Tenant(id=site.id, name=slug, slug=slug, domain=f"{slug}.test"))
                await session.flush()
                session.add_all(
                    (
                        User(
                            id=site.user,
                            tenant_id=site.id,
                            name="Renter",
                            email=f"renter@{slug}.test",
                        ),
                        CategoryRecord(id=site.category, tenant_id=site.id, name=slug, slug=slug),
                        TenantSettingsRecord(
                            tenant_id=site.id, policies={"reminder_hours_before": ahead}
                        ),
                    )
                )
        yield engine, first, other, datetime.now(UTC)
    finally:
        async with sessions.begin() as session:
            await session.execute(delete(Tenant).where(Tenant.id.in_((first.id, other.id))))
        await engine.dispose()


async def add_rental(
    session: AsyncSession, site: Site, end: datetime, *, status: RentalStatus = "active"
) -> RentalRecord:
    rental_id, lot_id, occupancy_id = uuid4(), uuid4(), uuid4()
    name = f"lot-{lot_id.hex[:16]}"
    start = end - timedelta(hours=6)
    session.add(
        LotRecord(
            id=lot_id,
            tenant_id=site.id,
            category_id=site.category,
            slug=name,
            name=name,
            rental_unit="hour",
            allowed_durations=[1],
            status="active",
        )
    )
    await session.flush()
    session.add(
        OccupancyRecord(
            id=occupancy_id,
            tenant_id=site.id,
            lot_id=lot_id,
            kind="booking",
            period=Range(start, end, bounds="[)"),
            ref_id=rental_id,
        )
    )
    row = RentalRecord(
        id=rental_id,
        tenant_id=site.id,
        user_id=site.user,
        lot_id=lot_id,
        occupancy_id=occupancy_id,
        variant_id=uuid4(),
        battery_count=0,
        start_time=start,
        end_time=end,
        price_minor=100,
        currency="RUB",
        status=status,
        cancellation_deadline=start - timedelta(hours=24),
    )
    session.add(row)
    await session.flush()
    return row


async def run(engine: AsyncEngine, site: Site, now: datetime, job: Job, limit: int = 10) -> int:
    async with (
        engine.connect() as connection,
        worker_session(connection, site.id) as session,
        session.begin(),
    ):
        return await job(session, now, limit, "reminder-test")


async def test_reminder_respects_tenant_window_active_status_and_deduplication(
    database: tuple[AsyncEngine, Site, Site, datetime],
) -> None:
    engine, site, other, now = database
    sessions = create_session_factory(engine)
    async with sessions.begin() as session:
        first = await add_rental(session, site, now + timedelta(minutes=20))
        edge = await add_rental(session, site, now + timedelta(hours=2))
        await add_rental(session, site, now + timedelta(hours=2, seconds=1))
        await add_rental(session, site, now + timedelta(minutes=5), status="booked")
        await add_rental(session, site, now, status="active")
        await add_rental(session, site, now - timedelta(minutes=1), status="overdue")
        other_edge = await add_rental(session, other, now + timedelta(hours=1))
        await add_rental(session, other, now + timedelta(hours=1, seconds=1))
    enqueue = JOBS["rental_reminders"]

    assert await run(engine, site, now, enqueue, limit=1) == 1
    assert await run(engine, site, now, enqueue, limit=1) == 1
    assert await run(engine, site, now, enqueue) == 0
    assert await run(engine, other, now, enqueue) == 1
    async with sessions.begin() as session:
        stored = await session.get_one(RentalRecord, first.id)
        stored.end_time = now + timedelta(hours=1, minutes=30)
    assert await run(engine, site, now, enqueue) == 0

    async with sessions() as session:
        messages = (
            await session.scalars(
                select(OutboxMessageRecord).where(
                    OutboxMessageRecord.tenant_id.in_((site.id, other.id))
                )
            )
        ).all()
        assert {(row.tenant_id, row.entity_id, row.user_id) for row in messages} == {
            (site.id, first.id, site.user),
            (site.id, edge.id, site.user),
            (other.id, other_edge.id, other.user),
        }
        assert all(
            row.event_type == "rental.ending_soon" and row.channel is None for row in messages
        )


@pytest.mark.parametrize("late", ["closed", "expired"])
async def test_queued_reminders_are_rechecked_by_both_delivery_channels(
    database: tuple[AsyncEngine, Site, Site, datetime],
    monkeypatch: pytest.MonkeyPatch,
    late: str,
) -> None:
    engine, site, _, now = database
    sessions = create_session_factory(engine)
    async with sessions.begin() as session:
        rental = await add_rental(session, site, now + timedelta(minutes=20))
        keys = generate_vapid_keypair()
        settings = await session.get_one(TenantSettingsRecord, site.id)
        settings.vapid_public_key = keys.public_key
        settings.vapid_private_key_enc = SecretBox.from_settings(DEMO_KEY).encrypt(
            keys.private_key, context=f"vapid:{site.id}"
        )
        session.add(
            PushSubscriptionRecord(
                tenant_id=site.id,
                user_id=site.user,
                endpoint="https://fcm.googleapis.com/fcm/send/demo",
                p256dh=keys.public_key,
                auth="AAECAwQFBgcICQoLDA0ODw",
            )
        )
    assert await run(engine, site, now, JOBS["rental_reminders"]) == 1

    push = create_push_jobs(
        PushSettings.model_validate(
            {
                "enabled": True,
                "subject": "mailto:local@example.test",
                "SECURITY_KEY": DEMO_KEY,
            }
        )
    )
    assert await run(engine, site, now, push["notification_routing"]) == 1
    async with sessions.begin() as session:
        row = await session.get_one(RentalRecord, rental.id)
        if late == "closed":
            row.status = "completed"
            row.completed_at = now
            row.closed_by = site.user
            row.close_comment = "Returned"
        else:
            row.end_time = now - timedelta(seconds=1)
        session.add(
            OutboxMessageRecord(
                tenant_id=site.id,
                entity_id=rental.id,
                user_id=site.user,
                event_type="rental.ending_soon",
                channel="email",
                available_at=now,
            )
        )

    async def forbidden(self: object, **kwargs: object) -> None:
        pytest.fail("expired rental reminder reached an external transport")

    monkeypatch.setattr("src.infrastructure.email.smtp.SmtpEmailSender.send", forbidden)
    monkeypatch.setattr("src.infrastructure.push.sender.WebPushSender.send", forbidden)
    email = create_email_job(
        SmtpSettings(
            host="127.0.0.1",
            from_address="test@example.test",
            security="plain",
        ),
        push_routing_enabled=True,
    )
    assert email is not None
    assert await run(engine, site, now, push["push_delivery"]) == 1
    assert await run(engine, site, now, email) == 1
    async with sessions() as session:
        statuses = (
            await session.scalars(
                select(OutboxMessageRecord.status).where(
                    OutboxMessageRecord.tenant_id == site.id,
                    OutboxMessageRecord.entity_id == rental.id,
                )
            )
        ).all()
        assert statuses == ["processed"] * 3


async def test_tenant_without_settings_uses_default_reminder_hour(
    database: tuple[AsyncEngine, Site, Site, datetime],
) -> None:
    engine, site, _, now = database
    sessions = create_session_factory(engine)
    async with sessions.begin() as session:
        settings = await session.get_one(TenantSettingsRecord, site.id)
        await session.delete(settings)
        due = await add_rental(session, site, now + timedelta(hours=1))
        await add_rental(session, site, now + timedelta(hours=1, seconds=1))
    assert await run(engine, site, now, JOBS["rental_reminders"]) == 1
    async with sessions() as session:
        actual = await session.scalar(
            select(OutboxMessageRecord.entity_id).where(OutboxMessageRecord.tenant_id == site.id)
        )
        assert actual == due.id
