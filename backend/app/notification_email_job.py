from datetime import datetime
from typing import Literal
from uuid import UUID

from prometheus_client import CollectorRegistry, Counter
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, User
from app.worker_jobs import Job
from src.application.services.outbox import OutboxConsumer
from src.application.services.provisioning import DOMAIN_LABEL
from src.domain.entities.notification_preferences import email_allowed
from src.domain.entities.outbox_message import OutboxMessage
from src.infrastructure.email import EMAIL_EVENT_TYPES, NotificationEmailRenderer, SmtpEmailSender
from src.infrastructure.email.smtp import SmtpDeliveryError
from src.infrastructure.postgres.repositories.outbox_repository import OutboxRepository


class SmtpSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WORKER_SMTP_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    host: str | None = Field(default=None, min_length=1)
    from_address: str | None = Field(default=None, min_length=1)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["plain", "starttls", "tls"] = "starttls"
    timeout_seconds: float = Field(default=5, gt=0, le=10)
    username: str | None = Field(default=None, min_length=1)
    password: SecretStr | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_settings(self) -> "SmtpSettings":
        if (self.host is None) != (self.from_address is None):
            raise ValueError("WORKER_SMTP_HOST and WORKER_SMTP_FROM_ADDRESS must be set together")
        if (self.username is None) != (self.password is None):
            raise ValueError("WORKER_SMTP_USERNAME and WORKER_SMTP_PASSWORD must be set together")
        if self.username and (self.security == "plain" or not self.host):
            raise ValueError("SMTP authentication requires an SMTP host and TLS")
        return self


class EmailDispatchError(RuntimeError):
    """A retryable email failure whose message is safe to persist."""


class EmailOutboxHandler:
    def __init__(
        self, session: AsyncSession, renderer: NotificationEmailRenderer, sender: SmtpEmailSender
    ) -> None:
        self._session = session
        self._renderer = renderer
        self._sender = sender
        self.sent = False
        self._tenant_id = UUID(str(session.info["tenant_id"]))

    async def handle(self, message: OutboxMessage) -> None:
        if message.user_id is None:
            return
        recipient = (
            await self._session.execute(
                select(User.email, User.role, User.notification_preferences).where(
                    User.tenant_id == self._tenant_id, User.id == message.user_id, User.is_active
                )
            )
        ).one_or_none()
        if recipient is None:
            return
        email, role, preferences = recipient
        if not email_allowed(preferences, message.event_type, role):
            return
        domain = await self._session.scalar(
            select(Tenant.domain).where(Tenant.id == self._tenant_id, Tenant.is_active)
        )
        if not domain:
            return
        if len(domain) > 253 or not all(
            DOMAIN_LABEL.fullmatch(label) for label in domain.split(".")
        ):
            raise EmailDispatchError("invalid_notification_domain")

        try:
            rendered = self._renderer.render(message.event_type, tenant_origin=f"https://{domain}")
            await self._sender.send(recipient=email, email=rendered, message_id=message.id)
            self.sent = True
        except SmtpDeliveryError:
            raise EmailDispatchError("smtp_delivery_failed") from None
        except ValueError:
            raise EmailDispatchError("invalid_email_data") from None


def create_email_job(
    settings: SmtpSettings,
    *,
    registry: CollectorRegistry | None = None,
    push_routing_enabled: bool = False,
) -> Job | None:
    if settings.host is None:
        return None
    assert settings.from_address is not None
    renderer = NotificationEmailRenderer()
    sender = SmtpEmailSender(
        host=settings.host,
        port=settings.port,
        from_address=settings.from_address,
        timeout_seconds=settings.timeout_seconds,
        security=settings.security,
        username=settings.username,
        password=settings.password.get_secret_value() if settings.password else None,
    )

    outcomes = Counter(
        "worker_email_delivery_attempts",
        "Outbox email delivery attempt outcomes",
        ("outcome",),
        registry=registry,
    )
    for outcome in ("sent", "skipped", "retry", "failed"):
        outcomes.labels(outcome)

    async def dispatch(session: AsyncSession, now: datetime, batch_size: int, trace_id: str) -> int:
        repository = OutboxRepository(
            session,
            event_types=EMAIL_EVENT_TYPES,
            route="explicit_email" if push_routing_enabled else "email",
        )
        # Keep successful sends in independent transactions because SMTP is not transactional.
        handler = EmailOutboxHandler(session, renderer, sender)
        result = await OutboxConsumer(repository).process_once(
            handler,
            now=now,
            limit=1,
            retry_errors=EmailDispatchError,
        )
        if result.claimed:
            outcome = "sent" if handler.sent else "skipped"
            if result.failed:
                outcome = "failed"
            elif result.retried:
                outcome = "retry"
            outcomes.labels(outcome).inc()
        return result.claimed

    return dispatch
