import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from prometheus_client import CollectorRegistry, Counter
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.worker_jobs import Job
from src.application.services.outbox import RETRY_DELAYS_MINUTES, OutboxConsumer
from src.domain.entities.notification_preferences import (
    applicable_events,
    email_allowed,
    locked_events,
    push_enabled,
)
from src.domain.entities.outbox_message import OutboxMessage
from src.infrastructure.email.renderer import EMAIL_EVENT_TYPES, push_content
from src.infrastructure.postgres.models.tenant_settings_record import TenantSettingsRecord
from src.infrastructure.postgres.repositories.outbox_repository import OutboxRepository
from src.infrastructure.postgres.repositories.push_subscription_repository import (
    PushSubscriptionRepository,
)
from src.infrastructure.postgres.repositories.rental_reminder_repository import (
    RentalReminderRepository,
)
from src.infrastructure.push.sender import PushSendKind, WebPushSender
from src.infrastructure.security.secret_box import SecretBox, decode_key


class PushSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WORKER_PUSH_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    enabled: bool = False
    subject: str | None = None
    timeout_seconds: float = Field(default=5, gt=0, le=10)
    security_key: SecretStr | None = Field(default=None, validation_alias="SECURITY_KEY")
    security_key_id: str = Field(default="primary", validation_alias="SECURITY_KEY_ID")
    security_previous_keys: dict[str, SecretStr] = Field(
        default_factory=dict, validation_alias="SECURITY_PREVIOUS_KEYS"
    )

    @model_validator(mode="after")
    def enabled_settings(self) -> "PushSettings":
        if not self.enabled:
            return self
        if not self.subject or not self.security_key:
            raise ValueError("Web Push requires WORKER_PUSH_SUBJECT and SECURITY_KEY")
        if not _valid_contact(self.subject):
            raise ValueError("WORKER_PUSH_SUBJECT must be a mailto or HTTPS contact")
        if self.security_key_id in self.security_previous_keys:
            raise ValueError("Active and previous Web Push encryption key IDs must differ")
        for id_, secret in {
            self.security_key_id: self.security_key,
            **self.security_previous_keys,
        }.items():
            if not re.fullmatch(r"[a-z0-9_-]{1,32}", id_):
                raise ValueError("Invalid Web Push encryption key ID")
            value = secret.get_secret_value()
            if not re.fullmatch(r"[A-Za-z0-9_-]{43}=?", value):
                raise ValueError("Invalid Web Push encryption key")
            decode_key(value)
        return self


def _valid_contact(value: str) -> bool:
    if len(value) > 256 or not value.isascii() or any(not 33 <= ord(c) <= 126 for c in value):
        return False
    try:
        contact = urlsplit(value)
        port = contact.port
    except ValueError:
        return False
    if contact.scheme == "mailto":
        return bool(
            not contact.netloc
            and not contact.query
            and not contact.fragment
            and re.fullmatch(r"[^@]+@[a-zA-Z0-9.-]+", contact.path)
        )
    return bool(
        contact.scheme == "https"
        and contact.hostname
        and contact.username is None
        and (port is None or port > 0)
    )


class PushRetry(RuntimeError):
    """A retryable Web Push error with no provider or credential details."""


class PushRejected(RuntimeError):
    """No subscription accepted the notification after a permanent rejection."""

    def __init__(self, message: OutboxMessage) -> None:
        self.message = message
        super().__init__("web_push_rejected")


async def recipient_settings(
    session: AsyncSession, message: OutboxMessage
) -> tuple[str, dict[str, object]] | None:
    tenant_id = UUID(str(session.info["tenant_id"]))
    row = (
        await session.execute(
            select(User.role, User.notification_preferences).where(
                User.tenant_id == tenant_id, User.id == message.user_id, User.is_active
            )
        )
    ).one_or_none()
    if row is None or message.event_type not in applicable_events(row.role):
        return None
    return row.role, row.notification_preferences


class NotificationRouter:
    def __init__(self, session: AsyncSession, outbox: OutboxRepository, now: datetime) -> None:
        self._session = session
        self._outbox = outbox
        self._now = now

    async def handle(self, message: OutboxMessage) -> None:
        recipient = await recipient_settings(self._session, message)
        if recipient is None:
            return
        if not await RentalReminderRepository(self._session).can_deliver(message):
            return
        role, preferences = recipient
        event = message.event_type
        critical = event in locked_events(role)
        use_push = critical or push_enabled(preferences)

        # Persist both channel decisions before any network delivery. The unique
        # outbox key makes rerouting an existing channel row harmless.
        if critical or (not use_push and email_allowed(preferences, event, role)):
            await self._outbox.enqueue_channel(message, "email", now=self._now)
        if use_push:
            await self._outbox.enqueue_channel(message, "push", now=self._now)


class PushOutboxHandler:
    def __init__(
        self,
        session: AsyncSession,
        outbox: OutboxRepository,
        sender: WebPushSender,
        secret_box: SecretBox,
        now: datetime,
    ) -> None:
        self._session = session
        self._tenant_id = UUID(str(session.info["tenant_id"]))
        self._outbox = outbox
        self._subscriptions = PushSubscriptionRepository(session)
        self._sender = sender
        self._secret_box = secret_box
        self._now = now
        self.outcome = "skipped"

    async def handle(self, message: OutboxMessage) -> None:
        recipient = await recipient_settings(self._session, message)
        if recipient is None or message.user_id is None:
            return
        if not await RentalReminderRepository(self._session).can_deliver(message):
            return
        role, preferences = recipient
        critical = message.event_type in locked_events(role)
        if critical or push_enabled(preferences):
            result = await self._send(message, message.user_id)
            if result == "expired":
                return
            if result == "sent":
                self.outcome = "sent"
                return
            if result == "retry":
                if message.attempts >= len(RETRY_DELAYS_MINUTES) and not critical:
                    await self._fallback(message, role, preferences)
                raise PushRetry("web_push_retryable")

            if result == "rejected":
                if not critical:
                    await self._fallback(message, role, preferences)
                raise PushRejected(message)

        if not critical:
            await self._fallback(message, role, preferences)

    async def _fallback(
        self, message: OutboxMessage, role: str, preferences: Mapping[str, object]
    ) -> None:
        if email_allowed(preferences, message.event_type, role):
            await self._outbox.enqueue_channel(message, "email", now=self._now)
            self.outcome = "fallback"

    async def _send(
        self, message: OutboxMessage, user_id: UUID
    ) -> Literal["sent", "retry", "rejected", "unavailable", "expired"]:
        subscriptions = await self._subscriptions.list_active(user_id, now=self._now)
        if not subscriptions:
            return "unavailable"
        encrypted = await self._session.scalar(
            select(TenantSettingsRecord.vapid_private_key_enc).where(
                TenantSettingsRecord.tenant_id == self._tenant_id
            )
        )
        if not encrypted:
            return "unavailable"
        try:
            private_key = self._secret_box.decrypt(encrypted, context=f"vapid:{self._tenant_id}")
        except ValueError:
            return "retry"

        title, body, url = push_content(message.event_type)
        payload = json.dumps(
            {"title": title, "body": body, "url": url, "tag": str(message.id)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        retryable = False
        rejected = False
        for subscription in subscriptions:
            if not await RentalReminderRepository(self._session).can_deliver(message):
                return "expired"
            result = await self._sender.send(
                endpoint=subscription.endpoint,
                p256dh=subscription.p256dh,
                auth=subscription.auth,
                vapid_private_key=private_key,
                payload=payload,
                ttl=300,
            )
            if result.kind is PushSendKind.ACCEPTED:
                return "sent"
            if result.kind is PushSendKind.GONE:
                await self._subscriptions.invalidate(
                    user_id, subscription.id, version=subscription.version, now=self._now
                )
            if result.kind is PushSendKind.RETRYABLE:
                retryable = True
            elif result.kind is PushSendKind.PERMANENT:
                rejected = True
        if retryable:
            return "retry"
        return "rejected" if rejected else "unavailable"


def create_push_jobs(
    settings: PushSettings, *, registry: CollectorRegistry | None = None
) -> dict[str, Job]:
    if not settings.enabled:
        return {}
    assert settings.security_key is not None and settings.subject is not None
    sender = WebPushSender(subject=settings.subject, timeout_seconds=settings.timeout_seconds)
    secret_box = SecretBox.from_settings(
        settings.security_key.get_secret_value(),
        key_id=settings.security_key_id,
        previous_keys={
            key: secret.get_secret_value()
            for key, secret in settings.security_previous_keys.items()
        },
    )
    metrics = Counter(
        "worker_push_delivery_attempts",
        "Outbox push delivery attempt outcomes",
        ("outcome",),
        registry=registry,
    )
    for label in ("sent", "fallback", "skipped", "retry", "failed"):
        metrics.labels(label)

    async def route(session: AsyncSession, now: datetime, batch_size: int, trace_id: str) -> int:
        outbox = OutboxRepository(session, event_types=EMAIL_EVENT_TYPES, route="unrouted")
        result = await OutboxConsumer(outbox).process_once(
            NotificationRouter(session, outbox, now),
            now=now,
            limit=batch_size,
            # Unexpected errors must roll back the routing transaction.
            retry_errors=PushRetry,
        )
        return result.claimed

    async def send(session: AsyncSession, now: datetime, batch_size: int, trace_id: str) -> int:
        outbox = OutboxRepository(session, event_types=EMAIL_EVENT_TYPES, route="push")
        handler = PushOutboxHandler(session, outbox, sender, secret_box, now)
        try:
            result = await OutboxConsumer(outbox).process_once(
                handler, now=now, limit=1, retry_errors=PushRetry
            )
        except PushRejected as rejected:
            await outbox.mark_failed(
                rejected.message.id,
                attempts=rejected.message.attempts + 1,
                available_at=now,
                status="failed",
                error=str(rejected),
            )
            metrics.labels("failed").inc()
            return 1
        if result.claimed:
            outcome = handler.outcome
            if result.failed:
                outcome = "failed"
            elif result.retried:
                outcome = "retry"
            metrics.labels(outcome).inc()
        return result.claimed

    return {"notification_routing": route, "push_delivery": send}
